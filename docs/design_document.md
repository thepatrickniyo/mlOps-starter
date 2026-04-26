# Deliverable 3: Zero-Downtime Deployment and Replication Design

## Scope and assumptions

This design covers Kigali primary infrastructure plus Raspberry Pi edge nodes (2GB RAM, intermittent links), with PostgreSQL logical replication and a FastAPI service. The goals are: no downtime during deploys, safe schema evolution, and predictable rollback.

Assumptions:
- Primary write traffic remains centralized in Kigali.
- Each clinic node serves local reads from its own logical replica.
- Edge nodes run Docker Compose, not Kubernetes.
- We can run a lightweight node agent (systemd timer + shell script) per clinic.

## a) RPi edge deployment strategy

### Release packaging and transport for intermittent connectivity

Do not rely on “node must be online when we push.” Use a pull-and-cache model:

1. Build immutable image tag in CI (`efiche-backend:<git-sha>`).
2. Publish both:
   - image to container registry,
   - signed release manifest (`release.json`) with image digest + schema compatibility metadata.
3. Each node agent polls for manifest every 5 minutes with jitter.
4. If manifest changed, agent attempts `docker pull <digest>` and stores state in `/var/lib/efiche/releases/`.
5. If offline, it keeps serving current container and retries later.

Why this works: deployments become eventually consistent, no central push dependency, and each node upgrades only when it has connectivity.

### Preventing failed deployment downtime

Use Compose with healthchecks, staged swap, and automatic fallback:

1. Keep current container running.
2. Start candidate container in parallel on alternate service name or project (`api_next`) with read-only warm-up checks.
3. Run local smoke checks against candidate (`/`, `/replication-health`, one read query).
4. If checks pass, switch traffic (reverse proxy label update or compose profile flip).
5. Keep previous container for rollback window (e.g., 30 min).

Minimal practical command for single-service replacement without touching DB sidecar:

```bash
docker compose up -d --no-deps --pull always api
```

Rollback command:

```bash
docker compose up -d --no-deps api@sha256:<previous_digest>
```

If pinned image aliases are unavailable locally, retain last known good tag in node state and run:

```bash
docker compose up -d --no-deps api
```

after setting `IMAGE_TAG` back to prior value in environment file.

### Deploying when replica is two hours behind

Embed schema compatibility in release manifest:

- `min_replica_schema_version`
- `requires_column = billing_status`

Node preflight gates deployment if:

1. replication lag exceeds threshold (for example > 1800s),
2. or local schema version table is below required migration step.

If gate fails, node defers deploy, reports status to efiche-ops, and keeps current version. This avoids booting code that expects a column not yet present due to delayed replication.

### Rollback procedure

1. Trigger rollback command in efiche-ops for affected node group.
2. Node agent reads previous stable release from local state file.
3. Executes:
   - `docker compose pull api@sha256:<previous>`
   - `docker compose up -d --no-deps api`
4. Re-runs smoke checks.
5. Marks node as `rollback_success` or `rollback_failed`.

Never rollback by deleting volumes blindly; replica data continuity is more important than immediate version parity.

## b) Migration safety in a replication context

### Order of operations

Run migration on **primary first**, then allow replication and/or managed schema sync to propagate to replicas before enabling application behaviors that depend on new constraints.

Reasoning:
- In logical replication, data changes originate from primary.
- If application writes new column before replica schema catches up, apply workers fail (“ghost column”).
- Therefore deploy sequence must separate schema introduction from feature activation.

### End-to-end process for `billing_status`

#### Phase 0: prechecks

1. Confirm all replicas healthy and lag under threshold.
2. Confirm publication/subscription states clean (`pg_stat_subscription`).
3. Enable feature flag `billing_status_reads=false`, `billing_status_writes=false`.

#### Phase 1: step-1 schema add

1. Apply `ALTER TABLE ... ADD COLUMN billing_status VARCHAR(20)` on primary.
2. Verify on primary and each replica:
   - `information_schema.columns` contains column.
3. Gate progression until all replicas report column present.

#### Phase 2: backfill

1. Run batched backfill job (script in `sql/20260426_add_billing_status_safe.sql` logic or app-managed worker).
2. Record progress metric: `remaining_nulls`.
3. Pause/resume capability after each batch to reduce load.
4. Keep `billing_status_reads=false`; code must tolerate null if accidental read occurs.

Verification before phase 3:
- `SELECT COUNT(*) FROM visit_invoices WHERE billing_status IS NULL;` equals zero on primary.
- Replica lag stays under agreed SLO while backfill runs.

#### Phase 3: enforce constraints

1. Add `CHECK ... NOT VALID`.
2. `VALIDATE CONSTRAINT`.
3. Set column default and `NOT NULL`.

Why this is safe:
- Validation is explicit and fails closed if any null rows remain.
- No assumption that backfill fully completed.

### Application behavior during transition window

During step 2:
- Writes: application should send `billing_status='pending'` for all new inserts in code path once step 1 is live.
- Reads: avoid hard dependency in business logic until step 3 completed globally.
- Serialization: API responses may omit or soft-default (`pending`) but should not crash on null.

Use two flags:
- `use_billing_status_for_logic` (off until step 3 done),
- `write_billing_status` (on after step 1 done).

### How efiche-ops detects partial failure in step 2

Add migration health probe:

1. Query primary null count:
   - `SELECT COUNT(*) AS remaining FROM visit_invoices WHERE billing_status IS NULL;`
2. Query backfill throughput:
   - rows/min moving average.
3. Alert conditions:
   - remaining count plateaus for >15 minutes,
   - replication lag increases continuously during backfill,
   - subscription errors mentioning missing column mapping.

Expose this in dashboard as:
- `migration_state`: `pending|running|stalled|validated`
- `remaining_rows`
- `estimated_time_to_zero`

## c) What not to automate in V1

### 1) Auto-trigger destructive schema sync on replica mismatch

Detection: replica apply worker errors indicating schema drift.

Technically feasible automation: run schema sync immediately.

Why we should not: in healthcare operations, wrong automated DDL on an edge node can make local read access unavailable during clinical hours. Better to page engineer, present guided runbook, and require explicit confirmation.

### 2) Auto-reinitialize a replica after long lag

Detection: lag > threshold for long duration.

Technically feasible automation: drop subscription and reseed.

Why we should not: high risk of accidental data divergence or long unavailability if network is unstable mid-reseed. Human review is needed to choose timing and verify disk/network health first.

### 3) Auto-rollback every failed healthcheck immediately

Detection: new app version fails one health probe.

Technically feasible automation: instant rollback.

Why we should not (in V1): intermittent clinic connectivity and dependency blips can cause false negatives. Safer policy is “N consecutive failures over M minutes + no active migration step” before suggesting rollback to operator.

### 4) Auto-restart database container on replication lag spike

Detection: lag trend grows rapidly.

Technically feasible automation: restart DB to “clear state.”

Why wrong: restarts often worsen lag and can interrupt local reads. Lag spikes should trigger diagnosis first (network, WAL pressure, long transaction), not blunt restart actions.

## Operational summary

The V1 system should automate **detection, gating, and safe defaults**, while keeping high-risk remediation human-approved. For this environment, “no downtime” is achieved less by aggressive auto-healing and more by conservative release orchestration, strong compatibility gates, and fast, deterministic rollback paths that preserve clinical continuity.
