import json
import os
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
import uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

app = FastAPI()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/efiche_replica",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_HISTORY_KEY = "replication:lag:history"
MAX_HISTORY = 5

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def classify_trend(history: list[dict[str, Any]]) -> str:
    # Trend calculation:
    # - use the last up to 5 readings ordered oldest -> newest
    # - compute delta = newest_lag - oldest_lag
    # - if delta >= 2.0 seconds => "growing"
    # - if delta <= -2.0 seconds => "recovering"
    # - otherwise => "stable"
    if len(history) < 2:
        return "stable"

    oldest = float(history[0]["lag_seconds"])
    newest = float(history[-1]["lag_seconds"])
    delta = newest - oldest

    if delta >= 2.0:
        return "growing"
    if delta <= -2.0:
        return "recovering"
    return "stable"


def is_degraded(history: list[dict[str, Any]]) -> bool:
    if len(history) < 3:
        return False

    newest = float(history[-1]["lag_seconds"])
    third_from_latest = float(history[-3]["lag_seconds"])
    return (newest - third_from_latest) > 10.0


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@app.get("/")
def read_root():
    return {"status": "Model API is online"}


@app.post("/predict")
def predict(data: dict):
    # Placeholder inference path.
    return {"prediction": "dummy_result", "input": data}


@app.get("/replication-health")
async def get_replication_health(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT now() - pg_last_xact_replay_timestamp() AS lag"))
    row = result.fetchone()
    lag_seconds = row[0].total_seconds() if row and row[0] else 0.0

    now = datetime.now(timezone.utc)
    reading = {"lag_seconds": float(lag_seconds), "recorded_at": to_iso_utc(now)}

    await redis_client.lpush(REDIS_HISTORY_KEY, json.dumps(reading))
    await redis_client.ltrim(REDIS_HISTORY_KEY, 0, MAX_HISTORY - 1)
    raw_history = await redis_client.lrange(REDIS_HISTORY_KEY, 0, MAX_HISTORY - 1)

    newest_first = [json.loads(item) for item in raw_history]
    history = list(reversed(newest_first))
    trend = classify_trend(history)
    degraded = is_degraded(history)

    return {
        "lag_seconds": round(float(lag_seconds), 3),
        "trend": trend,
        "degraded": degraded,
        "last_checked": to_iso_utc(now),
        "history": history,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)