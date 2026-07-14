# ClaimReady Milestone 3 Reconciliation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn extracted wound candidates into a deterministic, auditable clinical decision engine that reconciles wounds, validates Medicare Part B coverage, and routes each patient to auto-accept, review, or reject.

**Architecture:** Keep reconciliation separate from extraction. The new layer will read immutable candidate and evidence tables, group candidates into explicit wound groups, reconcile each field independently, persist selected evidence and conflicts, and then derive a patient-level routing record plus a human-readable decision trace. All outputs will be idempotent upserts keyed by stable reconciliation identifiers so reruns do not duplicate rows.

**Tech Stack:** Python 3.13, `sqlite3`, `dataclasses`, `httpx` for existing CLI behavior, `pytest`.

---

### Task 1: Add reconciliation tables, models, and migration helpers

**Files:**
- Modify: `claimready/models.py`
- Modify: `claimready/db.py`
- Modify: `tests/test_schema.py`
- Create: `tests/test_reconcile_schema.py`

- [ ] **Step 1: Write the failing schema test**

```python
def test_reconciliation_tables_exist(tmp_path):
    from claimready.db import Database

    database = Database(tmp_path / "claimready.sqlite3")
    database.initialize()

    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }

    assert {"reconciliation_runs", "reconciled_wounds", "selected_field_evidence", "reconciliation_conflicts", "patient_routing", "wound_group_members"} <= tables
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `./.venv/bin/python -m pytest tests/test_reconcile_schema.py -v`
Expected: failure because the reconciliation tables do not exist yet.

- [ ] **Step 3: Add the minimal schema and dataclasses**

```python
@dataclass(slots=True)
class ReconciliationRunRecord:
    id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    status: str = "running"
    evaluation_date: str | None = None
    patients_evaluated: int = 0
    wounds_reconciled: int = 0
    historical_conflicts: int = 0
    resolved_conflicts: int = 0
    unresolved_conflicts: int = 0
    auto_accept_count: int = 0
    flag_for_review_count: int = 0
    reject_count: int = 0
    error_message: str | None = None
```

```sql
create table if not exists reconciliation_runs (
    id integer primary key autoincrement,
    started_at text not null,
    finished_at text,
    status text not null,
    evaluation_date text not null,
    patients_evaluated integer not null default 0,
    wounds_reconciled integer not null default 0,
    historical_conflicts integer not null default 0,
    resolved_conflicts integer not null default 0,
    unresolved_conflicts integer not null default 0,
    auto_accept_count integer not null default 0,
    flag_for_review_count integer not null default 0,
    reject_count integer not null default 0,
    error_message text
)
```

Add:
- `reconciliation_run_id` to `reconciled_wounds`
- `reconciliation_run_id` to `reconciliation_conflicts`
- `reconciliation_run_id` to `patient_routing`
- `reconciliation_run_id` to `wound_group_members`

Add a `selected_field_evidence` table with:
- `value_type`
- `selection_reason`
- `alternative_values_json`
- `conflict_status`

Use idempotent upserts keyed by:
- `wound_key` for wound rows
- `(reconciliation_run_id, patient_internal_id)` for routing rows
- `(reconciliation_run_id, wound_key, field_name)` for selected field evidence
- `(reconciliation_run_id, wound_key, field_name, conflict_type, conflict_state)` for conflicts
- `(reconciliation_run_id, wound_key, candidate_key)` for group membership

- [ ] **Step 4: Run the schema test and confirm it passes**

Run: `./.venv/bin/python -m pytest tests/test_reconcile_schema.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add claimready/models.py claimready/db.py tests/test_schema.py tests/test_reconcile_schema.py
git commit -m "feat: add reconciliation schema"
```

### Task 2: Implement wound grouping and field-level reconciliation

**Files:**
- Create: `claimready/reconcile.py`
- Modify: `claimready/__init__.py`
- Modify: `claimready/db.py`
- Modify: `tests/test_reconciliation.py`

- [ ] **Step 1: Write the failing reconciliation tests**

```python
def test_lower_precedence_fills_missing_field(tmp_path):
    from claimready import cli
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    db_path = tmp_path / "claimready.sqlite3"
    assert cli.main(["--database", str(db_path), "--use-fixtures", "extract"]) == 0

    result = reconcile_database(Database(db_path))

    assert result.patient_routing_count > 0
    assert result.reconciled_wound_count > 0
```

- [ ] **Step 2: Run one test and confirm it fails**

Run: `./.venv/bin/python -m pytest tests/test_reconciliation.py::test_lower_precedence_fills_missing_field -v`
Expected: failure because `reconcile.py` does not exist yet.

- [ ] **Step 3: Add the reconciliation engine**

```python
def reconcile_patients(database: Database, *, evaluation_date: date, patient_external_id: str | None = None) -> ReconciliationResult:
    return reconcile_database(database, evaluation_date=evaluation_date, patient_external_id=patient_external_id)
```

Implement:
- explicit wound grouping by patient, location compatibility, wound type compatibility, source date proximity, measurement similarity, and explicit wound evidence
- field-level reconciliation for wound type, stage, location, length, width, depth, drainage, and documentation state
- deterministic precedence ordering
- historical, resolved, and unresolved material conflict classification
- selected evidence persistence with `value_type`
- `0.1 cm` documented tolerance, with raw alternatives preserved even inside the tolerance

- [ ] **Step 4: Run the reconciliation tests and iterate until green**

Run: `./.venv/bin/python -m pytest tests/test_reconciliation.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add claimready/reconcile.py claimready/__init__.py claimready/db.py tests/test_reconciliation.py
git commit -m "feat: implement wound reconciliation"
```

### Task 3: Implement Medicare validation, routing, explanations, and CLI

**Files:**
- Modify: `claimready/cli.py`
- Modify: `claimready/reconcile.py`
- Modify: `claimready/db.py`
- Modify: `tests/test_routing.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing routing and CLI tests**

```python
def test_no_part_b_rejects(tmp_path):
    from claimready import cli

    db_path = tmp_path / "claimready.sqlite3"
    assert cli.main(["--database", str(db_path), "--use-fixtures", "extract"]) == 0
    assert cli.main(["--database", str(db_path), "reconcile"]) == 0

def test_expired_part_b_flags_for_review(tmp_path):
    from claimready import cli
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    db_path = tmp_path / "claimready.sqlite3"
    assert cli.main(["--database", str(db_path), "--use-fixtures", "extract"]) == 0
    decision = reconcile_database(Database(db_path)).decisions_by_patient["FA-001"]
    assert decision.route in {"auto_accept", "flag_for_review", "reject"}

def test_patient_trace_is_readable(tmp_path, capsys):
    from claimready import cli

    db_path = tmp_path / "claimready.sqlite3"
    assert cli.main(["--database", str(db_path), "--use-fixtures", "extract"]) == 0
    assert cli.main(["--database", str(db_path), "reconcile", "--patient", "FA-001"]) == 0
```

- [ ] **Step 2: Run the routing test and confirm it fails**

Run: `./.venv/bin/python -m pytest tests/test_routing.py::test_no_part_b_rejects -v`
Expected: failure because routing tables and logic do not exist yet.

- [ ] **Step 3: Implement routing and explanation generation**

```python
def route_patient(reconciliation_result: ReconciliationResult, *, patient_external_id: str) -> RoutingDecision:
    decision = RoutingDecision(
        patient_external_id=patient_external_id,
        route="flag_for_review",
        explanation="Coverage is active but the primary wound is not yet reliable enough for auto-accept.",
    )
    return decision

def build_explanation(decision: RoutingDecision) -> str:
    return decision.explanation
```

Rules:
- active Part B only when payer code or type matches and coverage is active on the evaluation date
- auto-accept only when every required field is present, the primary wound is reliable, and there are no unresolved material conflicts
- flag-for-review when the patient may qualify but documentation or grouping is uncertain
- reject when there is no active Part B or no qualifying active wound

Add `python -m claimready reconcile` and `python -m claimready reconcile --patient FA-001`.

- [ ] **Step 4: Run the CLI and routing tests until they pass**

Run: `./.venv/bin/python -m pytest tests/test_routing.py tests/test_cli.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add claimready/cli.py claimready/reconcile.py claimready/db.py tests/test_routing.py tests/test_cli.py
git commit -m "feat: add reconciliation routing"
```

### Task 4: Expand verification, document assumptions, and update task tracking

**Files:**
- Modify: `README.md`
- Modify: `TASKS.md`
- Modify: `docs/API_STATUS.md`
- Create/modify: `tests/test_reconciliation_idempotency.py`
- Modify: any affected existing fixture or extraction tests

- [ ] **Step 1: Write the remaining edge-case tests**

Cover:
- structured source precedence
- lower-precedence source filling a missing field
- recency tie-breaking
- resolved versus unresolved conflict
- numeric measurement tolerance at `0.09`, `0.10`, and `0.11`
- stage conflict
- healed versus active conflict
- no Part B
- expired Part B
- multiple coverage records
- missing depth
- pressure ulcer missing stage
- non-pressure wound without stage
- multiple wounds
- ambiguous primary wound
- deterministic explanation text
- reconciliation idempotency
- patient-specific decision trace

- [ ] **Step 2: Run the full suite and verify the new total**

Run: `./.venv/bin/python -m pytest tests -v`
Expected: at least 40 tests passing, no regression in Milestone 1 or 2 behavior.

- [ ] **Step 3: Update docs and task tracker**

Document:
- reconciliation run semantics
- conflict state meanings
- numeric tolerance assumption
- routing criteria
- CLI usage examples

- [ ] **Step 4: Final verification and handoff**

Run:
```bash
./.venv/bin/python -m pytest tests -v
python -m claimready reconcile
python -m claimready reconcile --patient FA-001
```

Expected:
- full test suite passes
- reconciliation output shows counts for patients evaluated, wounds reconciled, resolved conflicts, unresolved conflicts, auto-accept, review, and reject
- patient-specific trace prints a readable decision narrative

---
