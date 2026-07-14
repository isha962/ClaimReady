from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable

from .db import Database
from .models import (
    CoverageRecord,
    ReconciledWoundRecord,
    ReconciliationConflictRecord,
    ReconciliationResult,
    ReconciliationRunRecord,
    RoutingDecision,
    SelectedFieldEvidenceRecord,
    WoundCandidateRecord,
    WoundGroupMemberRecord,
)


NUMERIC_TOLERANCE_CM = 0.1
REQUIRED_FIELDS = ("wound_type", "location", "length_cm", "width_cm", "depth_cm", "drainage_amount")
PRESSURE_ULCER_REQUIRED_FIELDS = REQUIRED_FIELDS + ("pressure_ulcer_stage",)
NUMERIC_FIELDS = {"length_cm", "width_cm", "depth_cm"}
TEXT_FIELDS = {"wound_type", "pressure_ulcer_stage", "location", "drainage_amount", "documentation_state"}


@dataclass(slots=True)
class _SourceContext:
    candidate: WoundCandidateRecord
    source_rank: int
    source_rank_label: str
    source_text: str
    source_note_type: str | None
    source_row: dict[str, Any]
    source_date_dt: datetime | None


@dataclass(slots=True)
class _FieldOption:
    candidate: _SourceContext
    field_name: str
    selected_value: Any
    value_type: str
    precedence_rank: int
    selection_reason: str


@dataclass(slots=True)
class _WoundGroup:
    wound_key: str
    patient_internal_id: int
    patient_external_id: str | None
    seed: _SourceContext
    members: list[_SourceContext]


@dataclass(slots=True)
class _GroupReconciliation:
    wound_record: ReconciledWoundRecord
    selected_fields: list[SelectedFieldEvidenceRecord]
    conflicts: list[ReconciliationConflictRecord]
    is_primary_ambiguous: bool
    completeness_score: int
    support_score: int


def reconcile_database(
    database: Database,
    *,
    evaluation_date: date | None = None,
    patient_external_id: str | None = None,
) -> ReconciliationResult:
    database.initialize()
    evaluation_date = evaluation_date or datetime.now(timezone.utc).date()
    evaluation_date_text = evaluation_date.isoformat()
    run_id = database.start_reconciliation_run(evaluation_date_text)
    run_started_at = _now()

    try:
        return _reconcile_database(database, run_id, evaluation_date, patient_external_id)
    except Exception as exc:
        database.finish_reconciliation_run(
            ReconciliationRunRecord(
                id=run_id,
                started_at=run_started_at,
                finished_at=_now(),
                status="failed",
                evaluation_date=evaluation_date_text,
                error_message=str(exc),
            )
        )
        raise


def reconcile_patients(
    database: Database,
    *,
    evaluation_date: date | None = None,
    patient_external_id: str | None = None,
) -> ReconciliationResult:
    return reconcile_database(database, evaluation_date=evaluation_date, patient_external_id=patient_external_id)


def format_patient_trace(decision: RoutingDecision, wounds: list[ReconciledWoundRecord], conflicts: list[ReconciliationConflictRecord]) -> list[str]:
    lines = [f"Decision trace for {decision.patient_external_id or decision.patient_internal_id}"]
    lines.append(f"Route: {decision.route}")
    lines.append(f"Coverage: {decision.coverage_status}")
    lines.append(f"Primary wound: {decision.primary_wound_key or 'none selected'}")
    if decision.missing_fields_json != "[]":
        lines.append(f"Missing fields: {decision.missing_fields_json}")
    if decision.conflicting_fields_json != "[]":
        lines.append(f"Conflicting fields: {decision.conflicting_fields_json}")
    lines.append(f"Recommended next action: {decision.recommended_next_action}")
    lines.append(f"Explanation: {decision.explanation}")
    if wounds:
        lines.append("Reconciled wounds:")
        for wound in wounds:
            lines.append(
                f"- {wound.wound_key}: {wound.wound_type or 'unknown'} / {wound.location or 'unknown'} / {wound.documentation_state or 'unknown'}"
            )
    if conflicts:
        lines.append("Conflicts:")
        for conflict in conflicts:
            lines.append(f"- {conflict.field_name}: {conflict.conflict_state} ({conflict.conflict_type})")
    return lines


def _reconcile_database(
    database: Database,
    run_id: int,
    evaluation_date: date,
    patient_external_id: str | None,
) -> ReconciliationResult:
    with database.connect() as connection:
        patient_rows = list(
            connection.execute(
                """
                select id, patient_id, facility_id, first_name, last_name, primary_payer_code
                from patients
                where (? is null or patient_id = ?)
                order by id
                """,
                (patient_external_id, patient_external_id),
            )
        )
        candidates = [dict(row) for row in connection.execute("select * from wound_candidates order by patient_internal_id, source_date, candidate_key")]
        coverage_rows = [dict(row) for row in connection.execute("select * from coverage_records order by patient_id, effective_from, id")]
        assessments_by_id = {int(row["id"]): dict(row) for row in connection.execute("select * from assessments")}
        notes_by_id = {int(row["id"]): dict(row) for row in connection.execute("select * from progress_notes")}

    candidates_by_patient: dict[int, list[_SourceContext]] = defaultdict(list)
    for candidate_row in candidates:
        candidate = _candidate_from_row(candidate_row)
        if patient_external_id and candidate.patient_external_id != patient_external_id:
            continue
        source_row = assessments_by_id.get(int(candidate.source_record_id)) if candidate.source_type == "assessment" else notes_by_id.get(int(candidate.source_record_id))
        source_context = _build_source_context(candidate, source_row or {})
        candidates_by_patient[candidate.patient_internal_id].append(source_context)

    coverage_by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in coverage_rows:
        coverage_by_patient[str(row["patient_id"])].append(row)

    wound_groups: list[_WoundGroup] = []
    for patient_row in patient_rows:
        pid = int(patient_row["id"])
        patient_external = str(patient_row["patient_id"])
        patient_candidates = candidates_by_patient.get(pid, [])
        wound_groups.extend(_group_candidates(pid, patient_external, patient_candidates, run_id))

    persisted_group_members: list[WoundGroupMemberRecord] = []
    reconciled_wounds: list[ReconciledWoundRecord] = []
    selected_evidence: list[SelectedFieldEvidenceRecord] = []
    conflicts: list[ReconciliationConflictRecord] = []
    routing_rows: list[RoutingDecision] = []
    decisions_by_patient: dict[str, RoutingDecision] = {}
    wounds_by_key: dict[str, ReconciledWoundRecord] = {}

    grouped_by_patient: dict[int, list[_WoundGroup]] = defaultdict(list)
    for group in wound_groups:
        grouped_by_patient[group.patient_internal_id].append(group)

    for patient_row in patient_rows:
        patient_internal_id = int(patient_row["id"])
        patient_external = str(patient_row["patient_id"])
        groups = grouped_by_patient.get(patient_internal_id, [])
        group_results = [
            _reconcile_group(run_id, group, evaluation_date)
            for group in groups
        ]

        persisted_group_members.extend(
            member
            for group in groups
            for member in _group_members_for_persistence(run_id, group)
        )
        reconciled_wounds.extend(result.wound_record for result in group_results)
        selected_evidence.extend(evidence for result in group_results for evidence in result.selected_fields)
        conflicts.extend(conflict for result in group_results for conflict in result.conflicts)

        decision, routing_conflicts = _route_patient(
            run_id,
            patient_internal_id,
            patient_external,
            evaluation_date,
            group_results,
            coverage_by_patient.get(patient_external, []),
            groups,
        )
        routing_rows.append(decision)
        decisions_by_patient[patient_external] = decision
        conflicts.extend(routing_conflicts)
    wounds_by_key = {wound.wound_key: wound for wound in reconciled_wounds}

    historical = sum(1 for conflict in conflicts if conflict.conflict_state == "historical")
    resolved = sum(1 for conflict in conflicts if conflict.conflict_state == "resolved")
    unresolved = sum(1 for conflict in conflicts if conflict.conflict_state == "unresolved_material")
    auto_accept = sum(1 for row in routing_rows if row.route == "auto_accept")
    review = sum(1 for row in routing_rows if row.route == "flag_for_review")
    reject = sum(1 for row in routing_rows if row.route == "reject")

    result = ReconciliationResult(
        reconciliation_run_id=run_id,
        patients_evaluated=len(patient_rows),
        wounds_reconciled=len(reconciled_wounds),
        historical_conflicts=historical,
        resolved_conflicts=resolved,
        unresolved_conflicts=unresolved,
        auto_accept_count=auto_accept,
        flag_for_review_count=review,
        reject_count=reject,
        decisions_by_patient=decisions_by_patient,
        wounds_by_key=wounds_by_key,
    )

    patient_ids = [int(row["id"]) for row in patient_rows]
    wound_keys = [wound.wound_key for wound in reconciled_wounds]
    run_record = ReconciliationRunRecord(
        id=run_id,
        started_at=_now(),
        finished_at=_now(),
        status="completed",
        evaluation_date=evaluation_date.isoformat(),
        patients_evaluated=result.patients_evaluated,
        wounds_reconciled=result.wounds_reconciled,
        historical_conflicts=result.historical_conflicts,
        resolved_conflicts=result.resolved_conflicts,
        unresolved_conflicts=result.unresolved_conflicts,
        auto_accept_count=result.auto_accept_count,
        flag_for_review_count=result.flag_for_review_count,
        reject_count=result.reject_count,
    )

    with database.transaction() as connection:
        database.clear_reconciliation_current_state(
            connection=connection,
            patient_internal_ids=patient_ids,
            wound_keys=wound_keys,
        )
        database.insert_wound_group_members(persisted_group_members, connection=connection)
        database.upsert_reconciled_wounds(reconciled_wounds, connection=connection)
        database.upsert_selected_field_evidence(selected_evidence, connection=connection)
        database.upsert_reconciliation_conflicts(conflicts, connection=connection)
        database.upsert_patient_routing(routing_rows, connection=connection)
        database.finish_reconciliation_run(run_record, connection=connection)

    return result


def _group_candidates(
    patient_internal_id: int,
    patient_external_id: str,
    candidates: list[_SourceContext],
    run_id: int,
) -> list[_WoundGroup]:
    groups: list[_WoundGroup] = []
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            item.source_rank,
            item.source_date_dt or datetime.min.replace(tzinfo=timezone.utc),
            item.candidate.source_record_id,
            item.candidate.candidate_key,
        ),
    )
    for candidate in sorted_candidates:
        best_group: _WoundGroup | None = None
        best_score = 0.0
        best_reason = ""
        second_best = 0.0
        for group in groups:
            score, reason = _match_group(candidate, group)
            if score > best_score:
                second_best = best_score
                best_score = score
                best_group = group
                best_reason = reason
            elif score > second_best:
                second_best = score
        if best_group is None or best_score < 0.55 or (best_score - second_best) < 0.15:
            wound_key = f"patient:{patient_internal_id}:wound:{len(groups) + 1}"
            new_group = _WoundGroup(
                wound_key=wound_key,
                patient_internal_id=patient_internal_id,
                patient_external_id=patient_external_id,
                seed=candidate,
                members=[candidate],
            )
            groups.append(new_group)
        else:
            best_group.members.append(candidate)
    return groups


def _match_group(candidate: _SourceContext, group: _WoundGroup) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []
    seed = group.seed

    if candidate.candidate.location and seed.candidate.location:
        if candidate.candidate.location == seed.candidate.location:
            score += 0.45
            reasons.append("matching location")
        elif _locations_compatible(candidate.candidate.location, seed.candidate.location):
            score += 0.35
            reasons.append("compatible location")
        else:
            return (-1.0, "location mismatch")
    else:
        score += 0.15
        reasons.append("location missing in one source")

    if candidate.candidate.wound_type and seed.candidate.wound_type:
        if candidate.candidate.wound_type == seed.candidate.wound_type:
            score += 0.35
            reasons.append("matching wound type")
        else:
            return (-1.0, "wound type mismatch")
    else:
        score += 0.10
        reasons.append("wound type missing in one source")

    date_score = _date_proximity_score(candidate.source_date_dt, seed.source_date_dt)
    if date_score:
        score += date_score
        reasons.append("source dates proximate")

    measurement_score = _measurement_similarity_score(candidate.candidate, seed.candidate)
    if measurement_score < 0:
        return (-1.0, "measurement mismatch")
    if measurement_score:
        score += measurement_score
        reasons.append("measurements compatible")

    if candidate.source_text != seed.source_text:
        if _is_explicit_narrative(candidate.source_text) and _is_explicit_narrative(seed.source_text):
            score += 0.1
            reasons.append("explicit wound evidence")

    return score, ", ".join(reasons) or "low confidence match"


def _reconcile_group(run_id: int, group: _WoundGroup, evaluation_date: date) -> _GroupReconciliation:
    selected_fields: list[SelectedFieldEvidenceRecord] = []
    conflicts: list[ReconciliationConflictRecord] = []
    field_values: dict[str, _FieldOption] = {}
    conflict_states: dict[str, str] = {}
    conflict_field_names: set[str] = set()

    for field_name in ("wound_type", "pressure_ulcer_stage", "location", "length_cm", "width_cm", "depth_cm", "drainage_amount", "documentation_state"):
        option = _select_field_option(group.members, field_name, evaluation_date)
        if option is None or option.selected_value is None:
            continue
        field_values[field_name] = option

        alt_values = _alternative_values_json(group.members, field_name, option.selected_value)
        conflict_state, conflict_type, threshold_json, source_records_json, source_dates_json, source_excerpts_json, explanation = _field_conflict_details(
            group.members,
            field_name,
            option.selected_value,
            option.precedence_rank,
        )
        if conflict_state and conflict_state != "none":
            conflict_states[field_name] = conflict_state
            conflict_field_names.add(field_name)
            conflicts.append(
                ReconciliationConflictRecord(
                    reconciliation_run_id=run_id,
                    patient_internal_id=group.patient_internal_id,
                    patient_external_id=group.patient_external_id,
                    wound_key=group.wound_key,
                    field_name=field_name,
                    conflict_type=conflict_type,
                    conflict_state=conflict_state,
                    selected_value=_stringify_value(option.selected_value),
                    alternative_values_json=alt_values,
                    threshold_json=threshold_json,
                    source_records_json=source_records_json,
                    source_dates_json=source_dates_json,
                    source_excerpts_json=source_excerpts_json,
                    explanation=explanation,
                    synced_at=_now(),
                )
            )

        selected_fields.append(
            SelectedFieldEvidenceRecord(
                reconciliation_run_id=run_id,
                wound_key=group.wound_key,
                candidate_key=option.candidate.candidate.candidate_key,
                field_name=field_name,
                selected_value=_stringify_value(option.selected_value),
                value_type=option.value_type,
                source_type=option.candidate.candidate.source_type,
                source_record_id=option.candidate.candidate.source_record_id,
                source_date=option.candidate.candidate.source_date,
                source_excerpt=option.candidate.candidate.source_excerpt,
                extraction_method=option.candidate.candidate.extraction_method,
                confidence=option.candidate.candidate.confidence,
                selection_reason=option.selection_reason,
                alternative_values_json=alt_values,
                conflict_status=conflict_states.get(field_name, "none"),
                precedence_rank=option.precedence_rank,
                synced_at=_now(),
            )
        )

    primary_candidate, primary_reason, is_ambiguous, support_score = _select_primary_candidate(group.members, field_values)
    completeness_score = sum(1 for field in REQUIRED_FIELDS if field_values.get(field))
    if field_values.get("wound_type") == "pressure_ulcer" and field_values.get("pressure_ulcer_stage"):
        completeness_score += 1
    documentation_state = str(field_values.get("documentation_state").selected_value) if field_values.get("documentation_state") else "unknown"
    is_active = documentation_state == "active"

    wound_record = ReconciledWoundRecord(
        reconciliation_run_id=run_id,
        wound_key=group.wound_key,
        patient_internal_id=group.patient_internal_id,
        patient_external_id=group.patient_external_id,
        primary_candidate_key=primary_candidate.candidate.candidate.candidate_key if primary_candidate else None,
        primary_source_type=primary_candidate.candidate.candidate.source_type if primary_candidate else None,
        primary_source_record_id=primary_candidate.candidate.candidate.source_record_id if primary_candidate else None,
        primary_source_date=primary_candidate.candidate.candidate.source_date if primary_candidate else None,
        primary_source_excerpt=primary_candidate.candidate.candidate.source_excerpt if primary_candidate else None,
        wound_type=field_values.get("wound_type").selected_value if field_values.get("wound_type") else None,
        pressure_ulcer_stage=field_values.get("pressure_ulcer_stage").selected_value if field_values.get("pressure_ulcer_stage") else None,
        location=field_values.get("location").selected_value if field_values.get("location") else None,
        length_cm=_numeric_value(field_values.get("length_cm")),
        width_cm=_numeric_value(field_values.get("width_cm")),
        depth_cm=_numeric_value(field_values.get("depth_cm")),
        drainage_amount=field_values.get("drainage_amount").selected_value if field_values.get("drainage_amount") else None,
        documentation_state=documentation_state,
        is_active_wound=is_active,
        is_primary_wound=False,
        confidence=_group_confidence(group.members, field_values),
        selection_reason=primary_reason,
        selected_at=_now(),
        synced_at=_now(),
    )
    return _GroupReconciliation(
        wound_record=wound_record,
        selected_fields=selected_fields,
        conflicts=conflicts,
        is_primary_ambiguous=is_ambiguous,
        completeness_score=completeness_score,
        support_score=support_score,
    )


def _select_field_option(
    members: list[_SourceContext],
    field_name: str,
    evaluation_date: date,
) -> _FieldOption | None:
    options: list[_FieldOption] = []
    for candidate in members:
        value = getattr(candidate.candidate, field_name)
        if value is None:
            continue
        precedence_rank = candidate.source_rank
        if field_name in NUMERIC_FIELDS:
            value_type = "numeric"
        else:
            value_type = "text"
        if value_type == "numeric":
            normalized = float(value)
            selected_value = normalized
        else:
            selected_value = value
        selection_reason = candidate.source_rank_label
        if candidate.source_rank > 1 and field_name in {"depth_cm", "length_cm", "width_cm"}:
            selection_reason = f"lower-precedence {candidate.source_rank_label} supplied missing measurement"
        options.append(
            _FieldOption(
                candidate=candidate,
                field_name=field_name,
                selected_value=selected_value,
                value_type=value_type,
                precedence_rank=precedence_rank,
                selection_reason=selection_reason,
            )
        )

    if not options:
        return None

    options.sort(
        key=lambda item: (
            item.precedence_rank,
            _recency_sort_key(item.candidate.source_date_dt),
            -item.candidate.candidate.confidence,
            item.candidate.candidate.candidate_key,
        )
    )
    winner = options[0]
    return winner


def _field_conflict_details(
    members: list[_SourceContext],
    field_name: str,
    selected_value: Any,
    selected_rank: int,
) -> tuple[str | None, str, str, str, str, str, str]:
    values = [getattr(member.candidate, field_name) for member in members if getattr(member.candidate, field_name) is not None]
    if len(values) <= 1:
        return ("none", "none", json.dumps({"numeric_tolerance_cm": NUMERIC_TOLERANCE_CM}), "[]", "[]", "[]", f"{field_name} selected from single source")

    source_records = [
        {
            "candidate_key": member.candidate.candidate_key,
            "source_type": member.candidate.source_type,
            "source_record_id": member.candidate.source_record_id,
            "source_date": member.candidate.source_date,
            "source_excerpt": member.candidate.source_excerpt,
            "value": _stringify_value(getattr(member.candidate, field_name)),
            "precedence_rank": member.source_rank,
        }
        for member in members
        if getattr(member.candidate, field_name) is not None
    ]
    source_dates_json = json.dumps([record["source_date"] for record in source_records], sort_keys=True)
    source_excerpts_json = json.dumps([record["source_excerpt"] for record in source_records], sort_keys=True)
    alternative_values_json = json.dumps(source_records, sort_keys=True)

    if field_name in NUMERIC_FIELDS:
        numeric_values = [float(value) for value in values if value is not None]
        threshold_json = json.dumps({"numeric_tolerance_cm": NUMERIC_TOLERANCE_CM}, sort_keys=True)
        max_delta = max(numeric_values) - min(numeric_values)
        if max_delta <= NUMERIC_TOLERANCE_CM + 1e-9:
            return ("historical", "measurement_disagreement", threshold_json, json.dumps(source_records, sort_keys=True), source_dates_json, source_excerpts_json, f"{field_name} differences are within documented tolerance")
        return ("unresolved_material", "measurement_disagreement", threshold_json, json.dumps(source_records, sort_keys=True), source_dates_json, source_excerpts_json, f"{field_name} differs by more than the documented tolerance")

    if field_name == "documentation_state":
        normalized = {str(value) for value in values}
        if "active" in normalized and any(value in {"healed", "resolved", "closed", "historical"} for value in normalized):
            threshold_json = json.dumps({"documentation_state": "active_vs_healed_or_resolved"}, sort_keys=True)
            return ("unresolved_material", "healed_vs_active_disagreement", threshold_json, alternative_values_json, source_dates_json, source_excerpts_json, "active and healed/resolved documentation disagree")
        return ("resolved", "documentation_state_disagreement", json.dumps({}, sort_keys=True), alternative_values_json, source_dates_json, source_excerpts_json, "documentation state differs but is not material")

    selected_text = _stringify_value(selected_value)
    if any(_stringify_value(value) != selected_text for value in values):
        if selected_rank == 1:
            state = "resolved"
        elif selected_rank <= 3:
            state = "resolved"
        else:
            state = "unresolved_material"
        threshold_json = json.dumps({}, sort_keys=True)
        conflict_type = {
            "pressure_ulcer_stage": "stage_disagreement",
            "wound_type": "wound_type_disagreement",
            "location": "location_disagreement",
            "drainage_amount": "drainage_disagreement",
        }.get(field_name, "field_disagreement")
        return (state, conflict_type, threshold_json, alternative_values_json, source_dates_json, source_excerpts_json, f"selected {field_name} from higher-precedence evidence")

    return ("none", "none", json.dumps({}, sort_keys=True), alternative_values_json, source_dates_json, source_excerpts_json, f"{field_name} values agree")


def _alternative_values_json(members: list[_SourceContext], field_name: str, selected_value: Any) -> str:
    records = [
        {
            "candidate_key": member.candidate.candidate_key,
            "source_type": member.candidate.source_type,
            "source_record_id": member.candidate.source_record_id,
            "source_date": member.candidate.source_date,
            "source_excerpt": member.candidate.source_excerpt,
            "value": _stringify_value(getattr(member.candidate, field_name)),
            "selected": _stringify_value(getattr(member.candidate, field_name)) == _stringify_value(selected_value),
        }
        for member in members
        if getattr(member.candidate, field_name) is not None
    ]
    return json.dumps(records, sort_keys=True)


def _select_primary_candidate(
    members: list[_SourceContext],
    field_values: dict[str, _FieldOption],
) -> tuple[_FieldOption | None, str, bool, int]:
    ranked = sorted(
        members,
        key=lambda member: (
            0 if member.candidate.documentation_state == "active" else 1,
            member.source_rank,
            -_complete_field_count(member),
            -_cross_source_support(member, members),
            -_severity_score(member.candidate),
            _date_sort_key(member.source_date_dt),
            member.candidate.candidate_key,
        ),
    )
    if not ranked:
        return None, "no candidates", False, 0
    first = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    first_rank = (
        0 if first.candidate.documentation_state == "active" else 1,
        first.source_rank,
        -_complete_field_count(first),
        -_cross_source_support(first, members),
        -_severity_score(first.candidate),
        _date_sort_key(first.source_date_dt),
    )
    second_rank = (
        0 if second.candidate.documentation_state == "active" else 1,
        second.source_rank,
        -_complete_field_count(second),
        -_cross_source_support(second, members),
        -_severity_score(second.candidate),
        _date_sort_key(second.source_date_dt),
    ) if second is not None else None
    ambiguous = second_rank is not None and first_rank == second_rank
    reason = "active over healed/resolved; recent reliable documentation; complete required fields; stronger cross-source support; severity as tie-breaker"
    option = _FieldOption(
        candidate=first,
        field_name="primary",
        selected_value=first.candidate.candidate_key,
        value_type="text",
        precedence_rank=first.source_rank,
        selection_reason=reason,
    )
    return option, reason, ambiguous, _cross_source_support(first, members)


def _route_patient(
    run_id: int,
    patient_internal_id: int,
    patient_external_id: str,
    evaluation_date: date,
    group_results: list[_GroupReconciliation],
    coverage_rows: list[dict[str, Any]],
    groups: list[_WoundGroup],
) -> tuple[RoutingDecision, list[ReconciliationConflictRecord]]:
    active_coverage = _select_active_part_b(coverage_rows, evaluation_date)
    coverage_status = active_coverage[0]
    coverage_row = active_coverage[1]
    active_part_b = coverage_status == "active_part_b"

    all_wounds = [result.wound_record for result in group_results]
    primary_group = _select_primary_group(group_results)
    primary_wound_key = primary_group.wound_record.wound_key if primary_group and not primary_group.is_primary_ambiguous else None

    missing_fields: list[str] = []
    conflicting_fields: list[str] = []
    routing_conflicts: list[ReconciliationConflictRecord] = []
    unresolved_conflicts = [conflict for result in group_results for conflict in result.conflicts if conflict.conflict_state == "unresolved_material"]
    for wound in all_wounds:
        required = PRESSURE_ULCER_REQUIRED_FIELDS if wound.wound_type == "pressure_ulcer" else REQUIRED_FIELDS
        for field_name in required:
            if getattr(wound, field_name) is None:
                missing_fields.append(field_name)
    if primary_wound_key is None and all_wounds:
        conflicting_fields.append("primary_wound")
        routing_conflicts.append(
            ReconciliationConflictRecord(
                reconciliation_run_id=run_id,
                patient_internal_id=patient_internal_id,
                patient_external_id=patient_external_id,
                wound_key=f"patient:{patient_internal_id}:primary",
                field_name="primary_wound",
                conflict_type="primary_wound_ambiguity",
                conflict_state="unresolved_material",
                selected_value=None,
                alternative_values_json=json.dumps([wound.wound_key for wound in all_wounds], sort_keys=True),
                threshold_json=json.dumps({}, sort_keys=True),
                source_records_json=json.dumps([wound.primary_candidate_key for wound in all_wounds], sort_keys=True),
                source_dates_json=json.dumps([wound.primary_source_date for wound in all_wounds], sort_keys=True),
                source_excerpts_json=json.dumps([wound.primary_source_excerpt for wound in all_wounds], sort_keys=True),
                explanation="Multiple wound groups remained clinically similar after deterministic scoring.",
                synced_at=_now(),
            )
        )

    if unresolved_conflicts:
        for conflict in unresolved_conflicts:
            if conflict.field_name not in conflicting_fields:
                conflicting_fields.append(conflict.field_name)
    all_conflict_fields = sorted(
        set(conflicting_fields)
        | {
            conflict.field_name
            for result in group_results
            for conflict in result.conflicts
        }
    )

    qualifying_wound = next((wound for wound in all_wounds if _is_qualifying_active_wound(wound)), None)
    qualifying_wound_present = qualifying_wound is not None
    active_wound_present = any(wound.is_active_wound for wound in all_wounds)
    primary_wound_reliable = primary_wound_key is not None and not unresolved_conflicts
    route, reason_codes, recommended_next_action, readiness_score, readiness_breakdown = _route_decision(
        active_part_b,
        qualifying_wound_present,
        active_wound_present,
        missing_fields,
        all_conflict_fields,
        unresolved_conflicts,
        primary_wound_reliable,
        primary_group,
        all_wounds,
    )
    explanation = _build_explanation(
        coverage_status=coverage_status,
        coverage_row=coverage_row,
        qualifying_wound=qualifying_wound,
        primary_group=primary_group,
        missing_fields=missing_fields,
        conflicting_fields=conflicting_fields,
        unresolved_conflicts=unresolved_conflicts,
        recommended_next_action=recommended_next_action,
    )

    decision = RoutingDecision(
        reconciliation_run_id=run_id,
        patient_internal_id=patient_internal_id,
        patient_external_id=patient_external_id,
        evaluation_date=evaluation_date.isoformat(),
        coverage_status=coverage_status,
        coverage_record_id=int(coverage_row["id"]) if coverage_row else None,
        coverage_record_snapshot_json=json.dumps(coverage_row, sort_keys=True) if coverage_row else None,
        active_part_b=active_part_b,
        qualifying_wound_present=qualifying_wound_present,
        primary_wound_key=primary_wound_key,
        route=route,
        explanation=explanation,
        missing_fields_json=json.dumps(sorted(set(missing_fields)), sort_keys=True),
        conflicting_fields_json=json.dumps(all_conflict_fields, sort_keys=True),
        recommended_next_action=recommended_next_action,
        readiness_score=readiness_score,
        readiness_breakdown_json=json.dumps(readiness_breakdown, sort_keys=True),
        routing_reason_codes_json=json.dumps(reason_codes, sort_keys=True),
        selected_at=_now(),
        synced_at=_now(),
    )
    return decision, routing_conflicts


def _route_decision(
    active_part_b: bool,
    qualifying_wound_present: bool,
    active_wound_present: bool,
    missing_fields: list[str],
    conflicting_fields: list[str],
    unresolved_conflicts: list[ReconciliationConflictRecord],
    primary_wound_reliable: bool,
    primary_group: _GroupReconciliation | None,
    all_wounds: list[ReconciledWoundRecord],
) -> tuple[str, list[str], str, float, dict[str, Any]]:
    required_fields_missing = sorted(set(missing_fields))
    conflicting_fields = sorted(set(conflicting_fields))
    reason_codes: list[str] = []
    coverage_score = 20.0 if active_part_b else 0.0
    wound_completeness = 0.0
    if primary_group:
        required = PRESSURE_ULCER_REQUIRED_FIELDS if primary_group.wound_record.wound_type == "pressure_ulcer" else REQUIRED_FIELDS
        present = sum(1 for field_name in required if getattr(primary_group.wound_record, field_name) is not None)
        wound_completeness = 60.0 * (present / len(required))
    conflict_score = 10.0 if not unresolved_conflicts else 0.0
    primary_score = 10.0 if primary_wound_reliable else 0.0
    readiness_score = round(coverage_score + wound_completeness + conflict_score + primary_score, 1)

    if not active_part_b:
        reason_codes.append("NO_ACTIVE_PART_B")
        return ("reject", reason_codes, "Do not route; active Medicare Part B is missing.", readiness_score, _readiness_breakdown(coverage_score, wound_completeness, conflict_score, primary_score, required_fields_missing, conflicting_fields))

    if not active_wound_present:
        reason_codes.append("ONLY_HEALED_OR_RESOLVED_WOUNDS")
        return ("reject", reason_codes, "Do not route; only healed or resolved wounds were reconciled.", readiness_score, _readiness_breakdown(coverage_score, wound_completeness, conflict_score, primary_score, required_fields_missing, conflicting_fields))

    if unresolved_conflicts or not primary_wound_reliable or required_fields_missing or not qualifying_wound_present:
        if unresolved_conflicts:
            reason_codes.append("UNRESOLVED_MATERIAL_CONFLICT")
        if not primary_wound_reliable:
            reason_codes.append("PRIMARY_WOUND_AMBIGUOUS")
        if required_fields_missing:
            reason_codes.append("MISSING_REQUIRED_FIELDS")
        if not qualifying_wound_present:
            reason_codes.append("NO_QUALIFYING_WOUND")
        return ("flag_for_review", reason_codes, "Review documentation before release.", readiness_score, _readiness_breakdown(coverage_score, wound_completeness, conflict_score, primary_score, required_fields_missing, conflicting_fields))

    reason_codes.extend(["ACTIVE_PART_B", "QUALIFYING_WOUND_PRESENT", "NO_UNRESOLVED_MATERIAL_CONFLICT"])
    return ("auto_accept", reason_codes, "Proceed to auto-accept.", readiness_score, _readiness_breakdown(coverage_score, wound_completeness, conflict_score, primary_score, required_fields_missing, conflicting_fields))


def _build_explanation(
    *,
    coverage_status: str,
    coverage_row: dict[str, Any] | None,
    qualifying_wound: ReconciledWoundRecord | None,
    primary_group: _GroupReconciliation | None,
    missing_fields: list[str],
    conflicting_fields: list[str],
    unresolved_conflicts: list[ReconciliationConflictRecord],
    recommended_next_action: str,
) -> str:
    coverage_text = "Active Medicare Part B coverage found." if coverage_status == "active_part_b" else "Medicare Part B coverage is not active."
    if qualifying_wound:
        wound_summary = _describe_wound(qualifying_wound)
        wound_text = f"A qualifying active wound was reconciled. Latest evidence documents {wound_summary}."
    else:
        wound_text = "No qualifying active wound was reconciled."
    primary_text = f"Primary wound selected: {primary_group.wound_record.wound_key}." if primary_group and not primary_group.is_primary_ambiguous else "Primary wound selection remains ambiguous."
    missing_text = "No required fields are missing." if not missing_fields else f"Missing fields: {', '.join(sorted(set(missing_fields)))}."
    conflict_text = "No unresolved documentation conflicts." if not unresolved_conflicts else f"Unresolved conflicts: {', '.join(sorted({conflict.field_name for conflict in unresolved_conflicts}))}."
    return " ".join([coverage_text, wound_text, primary_text, missing_text, conflict_text, f"Recommended next action: {recommended_next_action}"])


def _describe_wound(wound: ReconciledWoundRecord) -> str:
    parts: list[str] = []
    if wound.pressure_ulcer_stage:
        parts.append(f"Stage {wound.pressure_ulcer_stage}")
    if wound.wound_type:
        parts.append(wound.wound_type.replace("_", " "))
    if wound.location:
        parts.append(wound.location.lower())
    if wound.length_cm is not None and wound.width_cm is not None and wound.depth_cm is not None:
        parts.append(
            f"with complete measurements {wound.length_cm:g} x {wound.width_cm:g} x {wound.depth_cm:g} cm"
        )
    elif wound.length_cm is not None or wound.width_cm is not None or wound.depth_cm is not None:
        measurements = [f"{value:g}" for value in (wound.length_cm, wound.width_cm, wound.depth_cm) if value is not None]
        parts.append(f"with partial measurements {' x '.join(measurements)} cm")
    if wound.drainage_amount:
        parts.append(f"and {wound.drainage_amount} drainage")
    return " ".join(parts) if parts else "the wound"


def _readiness_breakdown(
    coverage_score: float,
    wound_completeness: float,
    conflict_score: float,
    primary_score: float,
    missing_fields: list[str],
    conflicting_fields: list[str],
) -> dict[str, Any]:
    return {
        "coverage_score": coverage_score,
        "wound_completeness_score": wound_completeness,
        "conflict_score": conflict_score,
        "primary_score": primary_score,
        "missing_fields": sorted(set(missing_fields)),
        "conflicting_fields": sorted(set(conflicting_fields)),
        "numeric_tolerance_cm": NUMERIC_TOLERANCE_CM,
        "score_maximum": 100,
    }


def _select_active_part_b(coverage_rows: list[dict[str, Any]], evaluation_date: date) -> tuple[str, dict[str, Any] | None]:
    active_rows = [
        row
        for row in coverage_rows
        if _is_active_part_b(row, evaluation_date)
    ]
    if not active_rows:
        return "no_active_part_b", None
    active_rows.sort(key=lambda row: (
        _sort_datetime(_parse_iso_datetime(row.get("effective_from"))),
        _sort_datetime(_parse_iso_datetime(row.get("last_modified_at"))),
        int(row.get("id", 0)),
    ), reverse=True)
    return "active_part_b", active_rows[0]


def _is_active_part_b(row: dict[str, Any], evaluation_date: date) -> bool:
    payer_code = str(row.get("payer_code") or "")
    payer_type = str(row.get("payer_type") or "")
    if payer_code != "MCB" and payer_type != "Medicare B":
        return False
    effective_from = _parse_iso_date(row.get("effective_from"))
    if effective_from and effective_from > evaluation_date:
        return False
    effective_to = _parse_iso_date(row.get("effective_to"))
    if effective_to and effective_to < evaluation_date:
        return False
    return True


def _is_qualifying_active_wound(wound: ReconciledWoundRecord) -> bool:
    required = PRESSURE_ULCER_REQUIRED_FIELDS if wound.wound_type == "pressure_ulcer" else REQUIRED_FIELDS
    return wound.is_active_wound and all(getattr(wound, field_name) is not None for field_name in required)


def _select_primary_group(group_results: list[_GroupReconciliation]) -> _GroupReconciliation | None:
    if not group_results:
        return None
    sorted_groups = sorted(
        group_results,
        key=lambda result: (
            0 if result.wound_record.is_active_wound else 1,
            -result.completeness_score,
            -result.support_score,
            -_severity_score_from_wound(result.wound_record),
            result.wound_record.primary_source_date or "",
            result.wound_record.wound_key,
        ),
    )
    if len(sorted_groups) > 1:
        first = sorted_groups[0]
        second = sorted_groups[1]
        if _primary_group_rank(first) == _primary_group_rank(second):
            first.is_primary_ambiguous = True
            return first
    for result in group_results:
        result.wound_record.is_primary_wound = False
    sorted_groups[0].wound_record.is_primary_wound = True
    return sorted_groups[0]


def _primary_group_rank(result: _GroupReconciliation) -> tuple[Any, ...]:
    return (
        0 if result.wound_record.is_active_wound else 1,
        -result.completeness_score,
        -result.support_score,
        -_severity_score_from_wound(result.wound_record),
        result.wound_record.primary_source_date or "",
    )


def _group_members_for_persistence(run_id: int, group: _WoundGroup) -> list[WoundGroupMemberRecord]:
    members: list[WoundGroupMemberRecord] = []
    for member in group.members:
        members.append(
            WoundGroupMemberRecord(
                reconciliation_run_id=run_id,
                wound_key=group.wound_key,
                candidate_key=member.candidate.candidate_key,
                match_score=1.0 if member is group.seed else _approximate_membership_score(member, group),
                match_reason="seed candidate" if member is group.seed else "grouped by location/type/date/measurement compatibility",
                synced_at=_now(),
            )
        )
    return members


def _approximate_membership_score(member: _SourceContext, group: _WoundGroup) -> float:
    score, _ = _match_group(member, group)
    return round(max(score, 0.0), 3)


def _candidate_from_row(row: dict[str, Any]) -> WoundCandidateRecord:
    return WoundCandidateRecord(
        candidate_key=row["candidate_key"],
        patient_internal_id=int(row["patient_internal_id"]),
        patient_external_id=row["patient_external_id"],
        source_type=row["source_type"],
        source_record_id=str(row["source_record_id"]),
        source_date=row.get("source_date"),
        wound_index=int(row["wound_index"]),
        documentation_state=row["documentation_state"],
        wound_type=row["wound_type"],
        pressure_ulcer_stage=row["pressure_ulcer_stage"],
        location=row["location"],
        length_cm=row["length_cm"],
        width_cm=row["width_cm"],
        depth_cm=row["depth_cm"],
        drainage_amount=row["drainage_amount"],
        extraction_method=row["extraction_method"],
        confidence=float(row["confidence"]),
        source_excerpt=row["source_excerpt"],
        raw_source_text=row["raw_source_text"],
        raw_source_json=row["raw_source_json"],
        conflict_count=int(row["conflict_count"]),
    )


def _build_source_context(candidate: WoundCandidateRecord, source_row: dict[str, Any]) -> _SourceContext:
    rank, rank_label = _classify_source(candidate, source_row)
    return _SourceContext(
        candidate=candidate,
        source_rank=rank,
        source_rank_label=rank_label,
        source_text=(candidate.raw_source_text or candidate.source_excerpt or json.dumps(source_row, sort_keys=True)),
        source_note_type=str(source_row.get("note_type")) if source_row else None,
        source_row=source_row,
        source_date_dt=_parse_iso_datetime(candidate.source_date),
    )


def _classify_source(candidate: WoundCandidateRecord, source_row: dict[str, Any]) -> tuple[int, str]:
    if candidate.source_type == "assessment":
        return 1, "complete structured assessment"
    note_text = str(source_row.get("note_text") or candidate.raw_source_text or candidate.source_excerpt or "")
    if _is_structured_labeled_note(note_text):
        return 2, "structured labeled clinical note"
    if _is_explicit_narrative(note_text):
        return 3, "narrative note with explicit evidence"
    return 4, "older or less explicit narrative evidence"


def _is_structured_labeled_note(text: str) -> bool:
    return bool(
        re.search(r"(?im)^\s*(location|wound type|drainage|length|width|depth)\s*:", text)
    )


def _is_explicit_narrative(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in ("sacrum", "sacral", "right heel", "left heel", "coccyx", "heel", "foot")
    ) or bool(re.search(r"\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?", text))


def _complete_field_count(candidate: _SourceContext) -> int:
    fields = ("wound_type", "pressure_ulcer_stage", "location", "length_cm", "width_cm", "depth_cm", "drainage_amount")
    return sum(1 for field_name in fields if getattr(candidate.candidate, field_name) is not None)


def _cross_source_support(candidate: _SourceContext, members: list[_SourceContext]) -> int:
    support = 0
    for other in members:
        if other is candidate:
            continue
        if candidate.candidate.wound_type and other.candidate.wound_type and candidate.candidate.wound_type == other.candidate.wound_type:
            support += 1
        if candidate.candidate.location and other.candidate.location and candidate.candidate.location == other.candidate.location:
            support += 1
    return support


def _severity_score(candidate: WoundCandidateRecord) -> float:
    stage = candidate.pressure_ulcer_stage
    if stage and stage.isdigit():
        return float(stage)
    if stage == "unstageable":
        return 4.5
    return 0.0


def _severity_score_from_wound(wound: ReconciledWoundRecord) -> float:
    stage = wound.pressure_ulcer_stage
    if stage and stage.isdigit():
        return float(stage)
    if stage == "unstageable":
        return 4.5
    return 0.0


def _locations_compatible(left: str, right: str) -> bool:
    left_norm = left.lower()
    right_norm = right.lower()
    if left_norm == right_norm:
        return True
    generic_pairs = {
        ("left heel", "heel"),
        ("right heel", "heel"),
        ("left foot", "foot"),
        ("right foot", "foot"),
        ("sacrum", "sacral"),
    }
    return (left_norm, right_norm) in generic_pairs or (right_norm, left_norm) in generic_pairs


def _measurement_similarity_score(left: WoundCandidateRecord, right: WoundCandidateRecord) -> float:
    values = []
    for field_name in ("length_cm", "width_cm", "depth_cm"):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value is None or right_value is None:
            continue
        delta = abs(float(left_value) - float(right_value))
        values.append(delta)
        if delta > 4.0:
            return -1.0
    if not values:
        return 0.05
    if max(values) <= NUMERIC_TOLERANCE_CM + 1e-9:
        return 0.25
    if max(values) <= 0.5:
        return 0.10
    return -1.0


def _date_proximity_score(left: datetime | None, right: datetime | None) -> float:
    if left is None or right is None:
        return 0.0
    delta_days = abs((left.date() - right.date()).days)
    if delta_days <= 7:
        return 0.15
    if delta_days <= 30:
        return 0.10
    if delta_days <= 60:
        return 0.05
    return 0.0


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _date_sort_key(value: datetime | None) -> tuple[int, str]:
    if value is None:
        return (1, "")
    return (0, value.isoformat())


def _recency_sort_key(value: datetime | None) -> tuple[int, str]:
    if value is None:
        return (1, "")
    return (0, _invert_string(value.isoformat()))


def _sort_datetime(value: datetime | None) -> tuple[int, str]:
    if value is None:
        return (-1, "")
    return (1, value.isoformat())


def _stringify_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _numeric_value(option: _FieldOption | None) -> float | None:
    if option is None or option.selected_value is None:
        return None
    return float(option.selected_value)


def _group_confidence(members: list[_SourceContext], fields: dict[str, _FieldOption]) -> float:
    if not fields:
        return 0.0
    return round(sum(option.candidate.candidate.confidence for option in fields.values()) / len(fields), 3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invert_string(value: str) -> str:
    return "".join(chr(255 - ord(char)) for char in value)
