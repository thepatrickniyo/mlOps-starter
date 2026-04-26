# Deliverable 1: Code Review and Written Analysis

## a) Migration Problem: Adding `billing_status` Safely

The one-line migration below is dangerous on a hot table with millions of rows:

```sql
ALTER TABLE visit_invoices
ADD COLUMN billing_status VARCHAR(20) NOT NULL DEFAULT 'pending';
```

Why it is wrong in this context:

1. **Lock risk under constant writes**: although newer PostgreSQL versions optimize some constant defaults, `ALTER TABLE` still takes a heavyweight table lock. On a table continuously written by application traffic, that can stall writes long enough to create real clinical impact.
2. **WAL burst and replica pressure**: if implementation or follow-up updates touch every row in one transaction, WAL volume spikes. Edge replicas over unreliable links can fall badly behind.
3. **No safety checkpoint**: schema + data + constraint are coupled. If anything fails mid-operation, there is no controlled recovery point.

The safe approach is the three-step migration in `sql/20260426_add_billing_status_safe.sql`:

1. **Step 1 (non-blocking schema prep)**: add the column as nullable and with no default.
   - Metadata-only change, shortest lock window.
   - Application can keep writing immediately.
2. **Step 2 (backfill existing rows)**: update `NULL` rows in batches (`LIMIT 10000` via `ctid`).
   - Spreads IO/WAL over time.
   - Allows replication to catch up between batches.
3. **Step 3 (enforce correctness defensively)**:
   - Add `CHECK (billing_status IS NOT NULL) NOT VALID`.
   - `VALIDATE CONSTRAINT` scans and fails if any nulls remain.
   - Only then set default + `NOT NULL`.

Order matters because enforcement before backfill causes immediate failures, while default before backfill does nothing for already existing rows. Validation before `SET NOT NULL` gives a deterministic safety gate if backfill was partial.

## b) Ghost Column Error During WAL Replay

Error:

```text
ERROR: column "billing_status" of relation "visit_invoices" does not exist
```

Typical sequence:

1. Primary deploy starts writing SQL referencing `billing_status` (or logical decoding publishes row changes including that column).
2. A replica subscription still has old schema (DDL not applied there yet, or replica replay is behind migration DDL LSN).
3. Apply worker on replica replays incoming change and cannot map column list to local table definition.
4. Replication slot for that subscriber stalls; lag grows.

Recovery without data loss:

1. **Freeze risky app writes** that reference new column (feature flag off or route writes to old shape only).
2. On primary, confirm migration state:
   - `\d+ visit_invoices`
   - `SELECT COUNT(*) FROM visit_invoices WHERE billing_status IS NULL;`
3. On failing replica, pause subscription:
   - `ALTER SUBSCRIPTION sub_rpi_node_7 DISABLE;`
4. Apply missing DDL on replica (same column type/default/constraint contract as primary).
5. Refresh subscription metadata:
   - `ALTER SUBSCRIPTION sub_rpi_node_7 REFRESH PUBLICATION;`
6. Re-enable:
   - `ALTER SUBSCRIPTION sub_rpi_node_7 ENABLE;`
7. Verify catch-up:
   - `SELECT * FROM pg_stat_subscription;`
   - check `latest_end_lsn` movement and lag decay in ops.

Where data loss can occur:

- Dropping/recreating subscription with `copy_data = false` while writes continue can create silent gaps.
- Advancing or dropping replication slots incorrectly can skip unapplied WAL.

Prevention:

- Do **not** drop slots/subscriptions first.
- Keep slot state, repair schema, then resume replay.
- If re-init is unavoidable, take a fresh base backup/snapshot and compare row counts/checksums for high-value tables before cutover.

## c) CI Pipeline Gaps and Added Checks

### Missing check 1: Migration safety gate (database)
- **Job**: `migration_safety_check` in `.gitlab-ci.yml`
- **What it runs**: boots disposable Postgres, applies migration script, and verifies no `NULL` remain.
- **Incidents prevented**:
  - migrations that pass syntax but fail at runtime,
  - constraints applied too early,
  - broken backfill scripts that leave partial data.

### Missing check 2: Configuration contract validation (application config)
- **Job**: `config_validation`
- **What it runs**: shell assertions that critical env vars exist (`DATABASE_URL`, `REDIS_URL`, split ops tokens).
- **Incidents prevented**:
  - deploy succeeds but app crash-loops on missing env vars,
  - dashboard starts in insecure fallback mode.

### Missing check 3: Python lint/static quality (non-PHP quality)
- **Job**: `python_lint`
- **What it runs**: `ruff check app`
- **Incidents prevented**:
  - broken imports, dead code paths, accidental debug leftovers,
  - style drift that hides real defects in frequent parallel changes.

### Missing check 4: Unit regression tests (functional behavior)
- **Job**: `unit_tests`
- **What it runs**: `pytest -q app/tests`
- **Incidents prevented**:
  - replication trend misclassification after refactor,
  - edge-case handling regressions in alert logic.

## d) Internal Memo: API Key Decision (190 words)

**Subject: Ops dashboard auth model for next 2 quarters**

We should **replace the single shared `OPS_API_KEY` with a two-token model plus action guardrails**, not full OAuth2 yet.

For a 4-engineer team, full identity infrastructure (OIDC, user lifecycle, JWT rotation, RBAC service) is probably overkill operationally today. But one shared key across read-only metrics and destructive actions is too risky for healthcare operations: key leakage gives immediate ability to restart containers, force schema sync, or trigger backfills across nodes.

Proposed V1.5:

1. `OPS_METRICS_TOKEN` for read-only endpoints.
2. `OPS_ADMIN_TOKEN` for mutating endpoints.
3. Require explicit `X-Action-Confirm: true` header for destructive actions.
4. Add request audit log (timestamp, action, token class, source IP, actor hint) to immutable storage.
5. Rotate both tokens quarterly and immediately on team membership change.

This keeps complexity low, can be implemented in one sprint, and materially reduces blast radius. If we grow beyond 4 engineers or need per-person accountability for compliance, we can then move to SSO-backed auth with scoped roles. For now, this is the best cost-to-risk balance.
