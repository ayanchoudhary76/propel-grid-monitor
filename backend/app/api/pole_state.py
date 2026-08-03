"""
Real-time pole state API — reads live energized/dark status from Redis.

All endpoints read from Redis, not PostgreSQL, because Redis holds the
current state derived from the telemetry stream.  A pole that has never
received telemetry has state ``"unknown"``.

Endpoints
---------
GET /api/poles/state           — all poles (or ?dt_id=X subset) with state
GET /api/poles/dark            — set of currently de-energized pole_ids
GET /api/poles/live            — count of currently energized poles
GET /api/poles/state/{pole_id} — detailed state for a single pole
"""
from __future__ import annotations

from typing import List, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis_dep
from app.database import get_db
from app.models.pole import Pole

router = APIRouter(prefix="/api/poles", tags=["pole-state"])

# Must match the keys used in ingest.py
POLE_HASH_KEY = "pole:{}"
POLES_LIVE_KEY = "poles:live"
POLES_DARK_KEY = "poles:dark"


# ── Response schemas ───────────────────────────────────────────────────────────


class PoleStateOut(BaseModel):
    """Real-time state for a single pole."""

    pole_id: str
    state: str                  # "energized" | "dark" | "unknown"
    energized: Optional[bool]   # None if no telemetry has been received
    last_seen: Optional[str]    # ISO-8601 device timestamp of the last event
    last_event: Optional[str]   # heartbeat | power_lost | power_restored | boot
    device_id: Optional[str]
    seq: Optional[int]          # last processed sequence number


class DarkPolesOut(BaseModel):
    count: int
    pole_ids: List[str]


class LivePolesOut(BaseModel):
    count: int


# ── Helpers ───────────────────────────────────────────────────────────────────


def _redis_hash_to_pole_state(pole_id: str, raw: dict) -> PoleStateOut:
    """Convert a raw Redis HGETALL response to a PoleStateOut."""
    if not raw:
        return PoleStateOut(
            pole_id=pole_id,
            state="unknown",
            energized=None,
            last_seen=None,
            last_event=None,
            device_id=None,
            seq=None,
        )

    energized_bool = raw.get("energized") == "1"
    seq_raw = raw.get("seq")
    return PoleStateOut(
        pole_id=pole_id,
        state="energized" if energized_bool else "dark",
        energized=energized_bool,
        last_seen=raw.get("last_seen"),
        last_event=raw.get("last_event"),
        device_id=raw.get("device_id"),
        seq=int(seq_raw) if seq_raw is not None else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/state",
    response_model=List[PoleStateOut],
    summary="Get real-time state for all poles (or a DT subset)",
    description=(
        "Returns the current energized/dark/unknown status for every pole, "
        "sourced from Redis.  Use the ``?dt_id=`` filter to limit results to "
        "a single distribution transformer (~20–120 poles) rather than "
        "fetching all ~3 700 at once.  State is fetched in a single pipeline "
        "round-trip regardless of pole count."
    ),
)
async def get_all_pole_states(
    dt_id: Optional[str] = Query(
        None,
        description="Filter to poles belonging to this distribution transformer, e.g. D-0001",
    ),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> List[PoleStateOut]:
    # 1. Fetch pole_ids from PostgreSQL (one query, indexed on dt_id)
    stmt = select(Pole.id).order_by(Pole.id)
    if dt_id:
        stmt = stmt.where(Pole.dt_id == dt_id)
    result = await db.execute(stmt)
    pole_ids: List[str] = [row[0] for row in result.fetchall()]

    if not pole_ids:
        return []

    # 2. Batch-fetch all Redis hashes in a single pipeline round-trip
    pipe = redis.pipeline(transaction=False)
    for pid in pole_ids:
        pipe.hgetall(POLE_HASH_KEY.format(pid))
    raw_states: List[dict] = await pipe.execute()

    return [
        _redis_hash_to_pole_state(pid, raw)
        for pid, raw in zip(pole_ids, raw_states)
    ]


@router.get(
    "/dark",
    response_model=DarkPolesOut,
    summary="List currently de-energized (dark) poles",
    description=(
        "Returns all pole_ids that have reported a ``power_lost`` event and "
        "have not yet reported ``power_restored`` or ``boot``.  Sourced "
        "directly from the ``poles:dark`` Redis set."
    ),
)
async def get_dark_poles(
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> DarkPolesOut:
    dark: set = await redis.smembers(POLES_DARK_KEY)
    sorted_ids = sorted(dark)
    return DarkPolesOut(count=len(sorted_ids), pole_ids=sorted_ids)


@router.get(
    "/live",
    response_model=LivePolesOut,
    summary="Count currently energized (live) poles",
    description=(
        "Returns the cardinality of the ``poles:live`` Redis set — i.e. the "
        "number of poles that are currently reporting as energized."
    ),
)
async def get_live_count(
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> LivePolesOut:
    count: int = await redis.scard(POLES_LIVE_KEY)
    return LivePolesOut(count=count)


@router.get(
    "/state/{pole_id}",
    response_model=PoleStateOut,
    summary="Get real-time state for a single pole",
    description=(
        "Returns the current energized/dark/unknown status, last event, and "
        "device metadata for the specified pole from Redis."
    ),
)
async def get_single_pole_state(
    pole_id: str,
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> PoleStateOut:
    raw: dict = await redis.hgetall(POLE_HASH_KEY.format(pole_id))
    return _redis_hash_to_pole_state(pole_id, raw)
