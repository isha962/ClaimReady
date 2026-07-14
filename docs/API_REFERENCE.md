# ClaimReady API Reference

All endpoints are read-only and powered by the current-state SQLite tables.

## `GET /api/summary`

Returns:

- total patients
- active Medicare Part B count
- auto accept count
- flag for review count
- reject count
- claim-ready rate
- unresolved conflict count
- most common missing field
- latest sync time
- latest reconciliation time

## `GET /api/patients`

Supports filtering, search, sorting, and pagination.

Filters:

- `facility_id`
- `route`
- `wound_type`
- `missing_field`
- `conflict_status`
- `minimum_readiness_score`
- `search`

## `GET /api/patients/{patient_external_id}`

Returns patient demographics, coverage evidence, diagnoses, routing decision, primary wound, reconciled wounds, selected field evidence, conflicts, and an audit section of raw records.

## `GET /api/facilities`

Returns facility-level route distribution, missing fields, conflict count, and wound-type mix.

## `GET /api/pipeline-health`

Returns the latest sync and reconciliation runs, endpoint failures, record counts, and extraction candidate counts.

## `GET /api/export/patients.csv`

Exports the routing table as CSV.
