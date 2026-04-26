# eFiche Zero-Downtime Replication Assignment

This repository contains the implementation and documents for the senior MLOps/Infrastructure challenge:

- FastAPI endpoint upgrade from `/replication-lag` to `/replication-health`
- Redis-backed lag history + trend/degraded classification
- Safe PostgreSQL three-step migration script for `billing_status`
- Improved GitLab CI pipeline with migration, config, lint, and unit-test gates
- Written analysis and deployment design docs

## Project Layout

- `app/app.py` FastAPI service and replication health endpoint
- `app/tests/test_replication_health.py` unit tests for trend classification
- `sql/20260426_add_billing_status_safe.sql` zero-downtime migration script
- `.gitlab-ci.yml` improved CI pipeline
- `docs/submission_analysis.md` deliverable 1 (a-d)
- `docs/design_document.md` deliverable 3 (a-c)

## Run Replication Health Locally

### 1) Start Redis (real Redis, local container)

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

### 2) Use a stubbed PostgreSQL replica query result

The main code path always runs a real SQL query (`SELECT now() - pg_last_xact_replay_timestamp()`), but for local simulation without a real replica, you can monkeypatch the DB dependency in a short dev runner.

Create `app/dev_stub_runner.py`:

```python
from datetime import timedelta
from app import app, get_db

class FakeResult:
    def fetchone(self):
        return (timedelta(seconds=4.2),)

class FakeSession:
    async def execute(self, *_args, **_kwargs):
        return FakeResult()

async def fake_get_db():
    yield FakeSession()

app.dependency_overrides[get_db] = fake_get_db
```

Run:

```bash
cd app
python -m pip install -r requirements.txt
uvicorn dev_stub_runner:app --reload --port 8080
```

Set environment (new terminal):

```bash
export REDIS_URL=redis://localhost:6379/0
```

Call endpoint:

```bash
curl http://localhost:8080/replication-health
```

## Run Unit Tests

```bash
cd app
python -m pip install -r requirements.txt
PYTHONPATH=. pytest -q tests
```

## Simulate a Growing Lag Trend Manually

Call `/replication-health` multiple times while changing the stubbed lag value upward between calls (for example: 1.0 -> 1.8 -> 2.9 -> 3.6 -> 4.2). The response should eventually return:

- `"trend": "growing"`
- a 5-point `history` ordered oldest first

If you want to reset history:

```bash
redis-cli DEL replication:lag:history
```

## Stubbed vs Real Components

### Real in main code path

- FastAPI route logic
- `redis.asyncio` client operations (`LPUSH`, `LTRIM`, `LRANGE`)
- SQL query execution against provided DB dependency

### Stubbed/mocked in tests or local simulation

- PostgreSQL replica query result (mocked in test/dev via dependency override)
- Trend test data series (synthetic lag values)

## Notes

- Trend logic is explicit in code comments inside `classify_trend()`.
- `degraded` becomes `true` when lag increases by more than 10 seconds across the latest 3 readings.
- Endpoint response includes `lag_seconds`, `trend`, `degraded`, `last_checked`, and `history`.
