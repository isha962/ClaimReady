# ClaimReady

ClaimReady is a production-minded backend and frontend scaffold for the ABI Frameworks hackathon project.

Milestone 1 focuses on:

- repository setup
- source record models
- SQLite persistence
- a resilient async PCC API client
- ingestion of patients, diagnoses, coverage, notes, and assessments
- tests for the database schema, retry behavior, and sync flow

Milestone 2 adds:

- structured extraction from assessment `raw_json`
- wound candidate extraction from SOAP, labeled, abbreviated prose, and narrative notes
- normalized candidate, provenance, and conflict tables
- a CLI extraction command for fixture-backed validation

Milestone 3 adds:

- candidate reconciliation into reconciled wounds
- deterministic routing and conflict traceability
- Medicare Part B validation and deterministic explanations

Milestone 4 adds:

- a FastAPI read-only API over current-state and audit tables
- a Next.js biller-facing interface
- CSV export, filtering, sorting, and traceability views

## Source reference

The source specification lives in:

- `reference/Hackathon-ABI-Frameworks/README.md`
- `reference/Hackathon-ABI-Frameworks/API.md`

Those files are read-only references only.

## Local setup

```bash
./.venv/bin/python -m pip install -e ".[dev]"
cd frontend && npm install
```

## Run tests

```bash
./.venv/bin/python -m pytest tests -q
cd frontend && npm run test
```

## Backend

Run the API:

```bash
./.venv/bin/uvicorn claimready.api:app --host 127.0.0.1 --port 8000
```

Run the fixture sync:

```bash
python -m claimready --use-fixtures
```

Check the live API:

```bash
python -m claimready check-api
```

Run reconciliation:

```bash
python -m claimready reconcile
```

## Frontend

Run the dashboard:

```bash
cd frontend && npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` when the frontend runs on a different port than the backend.

## API reference

The read-only dashboard API lives under `/api`:

- `GET /api/summary`
- `GET /api/patients`
- `GET /api/patients/{patient_external_id}`
- `GET /api/facilities`
- `GET /api/pipeline-health`
- `GET /api/export/patients.csv`

See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) for a summary of the response contract.

## Demo workflow

1. Start the backend API.
2. Start the frontend on port 3000.
3. Open the Command Center to review summary metrics.
4. Use Biller Work Queue to filter by route, facility, and wound type.
5. Open a patient detail page to inspect source excerpts, selected evidence, and conflict history.
6. Use Facility Intelligence and Pipeline Health for operational review.

## Screenshots

Add screenshots from the running frontend after local verification. The key views are:

- Command Center
- Biller Work Queue
- Patient Detail
- Facility Intelligence
- Pipeline Health

## Sync status rules

- A sync run is marked `completed` when all required facility patient-list fetches succeed.
- A sync run is marked `failed` when a required facility patient-list fetch fails after retries.
- Optional patient-level requests for diagnoses, coverage, notes, and assessments may fail without failing the run.
- Those optional failures still increment `failure_count` and are recorded in `failed_requests`.
- The sync close timestamp is stored in `finished_at`.

## Extraction rules

- Assessment `raw_json` is parsed into wound candidates when it contains structured wound fields.
- SOAP-style, labeled, and abbreviated prose notes are parsed into candidate wounds before any later reconciliation work.
- Missing values remain `NULL`; unsupported or malformed values are not inferred.
- The extractor preserves field-level provenance with source type, source id, source date, source excerpt, extraction method, and confidence.
- Candidate rows are rerunnable and are keyed by stable source identity plus wound index.

## Milestone 4 notes

- The dashboard only reads from current-state and audit tables.
- Every displayed number comes from the SQLite database.
- Fixture data is synthetic development data and should never be treated as clinical truth.
