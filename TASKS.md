# TASKS

## Milestone 1

- [x] Repository scaffold created
- [x] SQLite schema and source models added
- [x] Resilient PCC client and ingestion implemented
- [x] Fixture mode and live API checks implemented
- [x] Tests added for retries, clean failure handling, and idempotent sync

## Milestone 2

- [x] Parse structured assessment `raw_json`
- [x] Parse SOAP and labeled wound notes
- [x] Parse abbreviated prose measurements
- [x] Normalize wound type, stage, location, dimensions, and drainage
- [x] Create wound candidate records with provenance and conflicts
- [x] Add candidate, evidence, and conflict tables
- [x] Add extraction CLI command
- [x] Add tests for extraction formats and edge cases

## Milestone 3

- [x] Add reconciliation runs, wound groups, selected evidence, conflicts, and routing tables
- [x] Group wound candidates explicitly and persist auditable memberships
- [x] Reconcile field-level evidence deterministically with provenance and conflict state
- [x] Validate Medicare Part B coverage from coverage records only
- [x] Route patients to `auto_accept`, `flag_for_review`, or `reject`
- [x] Generate deterministic explanations and patient trace output
- [x] Add reconciliation CLI and patient trace mode
- [x] Add reconciliation tests, including numeric tolerance boundary coverage
- [x] Make reconciliation rerunnable without duplicating rows
- [x] Document the `0.1 cm` numeric tolerance assumption
- [x] Full test suite passing

## Next

- [x] Backend read-only API
- [x] Next.js biller-facing dashboard
- [x] CSV export and operational views
- [ ] Screenshot capture and demo polish
