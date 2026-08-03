"""
Telemetry ingestion API for the KSPDCL Fault Detection System.

Endpoints
---------
POST /api/telemetry        — single event ingestion
POST /api/telemetry/batch  — up to 500 events in one HTTP call

Design
------
Each message goes through three stages:

  1. **Deduplication** — INSERT ... ON CONFLICT DO NOTHING on (device_id, seq).
     Duplicate packets (e.g. from IoT retry logic) are silently discarded.

  2. **Persistence** — The TelemetryEvent row is committed to PostgreSQL with
     ``received_at = utcnow()`` (server clock, immune to device clock skew).

  3. **Real-time state update** — Redis is updated atomically via a pipeline:
       • ``pole:{pole_id}`` hash  — energized, last_seen, last_event, seq, device_id
       • ``poles:live`` set       — pole_ids reporting as energized
       • ``poles:dark`` set       — pole_ids reporting as de-energized
     State changes trigger a pub/sub publish to ``pole_state_changes`` for the
     fault-detection engine (built in a later module).

Stale-message handling
----------------------
Devices can buffer and re-transmit events up to 6 hours after the fact.
Stale messages are stored in PostgreSQL (full audit trail) but do NOT update
Redis.  A message is considered stale if its ``seq`` number is ≤ the highest
``seq`` already recorded in Redis for that device / pole.

Performance targets
-------------------
• ≥ 500 msg/s sustained  (single endpoint, repeated calls)
• 5 000 messages in 10 s (batch endpoint, 10 × 500-message bursts)

The batch endpoint uses:
  - One bulk ``INSERT ... RETURNING`` for all payloads
  - One Redis pipeline to fetch all current states
  - One Redis pipeline to apply all state updates
  - One Redis pipeline for all pub/sub publishes
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis_dep
from app.database import get_db
from app.models.pole import Pole
from app.models.telemetry import EventType, TelemetryEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])

# ── Redis key / channel constants ──────────────────────────────────────────────

POLE_HASH_KEY = "pole:{}"          # HSET with energized, last_seen, last_event, device_id, seq
POLES_LIVE_KEY = "poles:live"      # SET of energized pole_ids
POLES_DARK_KEY = "poles:dark"      # SET of de-energized pole_ids
STATE_CHANGE_CHANNEL = "pole_state_changes"   # Pub/sub channel for fault engine


# ── Pydantic request / response schemas ───────────────────────────────────────


class TelemetryPayload(BaseModel):
    """Single telemetry event from a pole-mounted IoT device."""

    device_id: str = Field(
        ...,
        max_length=100,
        description="Unique device identifier, e.g. KSPDB-SD07-D0112-4431",
        examples=["KSPDB-SD07-D0112-4431"],
    )
    pole_id: str = Field(
        ...,
        max_length=50,
        description="Pole ID the device is mounted on",
        examples=["P-024431"],
    )
    event: EventType = Field(
        ...,
        description="Event type: heartbeat | power_lost | power_restored | boot",
    )
    energized: bool = Field(
        ...,
        description="True if the pole is currently energized (device-reported)",
    )
    ts: datetime = Field(
        ...,
        description="Device-reported UTC timestamp (±90 s clock skew tolerated)",
    )
    seq: int = Field(
        ...,
        ge=0,
        description="Monotonic sequence number from device firmware (used for dedup and staleness)",
    )
    battery_mv: int = Field(
        ...,
        ge=0,
        le=5000,
        description="Battery voltage in millivolts",
    )
    rssi: int = Field(
        ...,
        ge=-150,
        le=0,
        description="RSSI in dBm (negative integer)",
    )
    fw: str = Field(
        ...,
        max_length=50,
        description="Firmware version string, e.g. '1.4.2'",
    )


class IngestResponse(BaseModel):
    """Response from the single-event ingest endpoint."""

    status: str           # "ok" | "duplicate"
    device_id: str
    pole_id: Optional[str] = None
    state_changed: Optional[bool] = None   # None for duplicates
    stale: Optional[bool] = None           # None for duplicates


class BatchIngestResponse(BaseModel):
    """Aggregate response from the batch ingest endpoint."""

    status: str
    total: int
    inserted: int
    duplicates: int
    stale: int            # inserted but not applied to Redis (seq too old)
    state_changes: int    # energized ↔ dark transitions published to pub/sub


# ── Internal helpers ──────────────────────────────────────────────────────────


def _new_energized_value(payload: TelemetryPayload) -> bool:
    """
    Determine the canonical energized state from an incoming payload.

    ``power_lost``              → always False (de-energized)
    ``power_restored`` / ``boot`` → always True  (energized)
    ``heartbeat``               → use the device-reported ``energized`` field
    """
    if payload.event == EventType.power_lost:
        return False
    if payload.event in (EventType.power_restored, EventType.boot):
        return True
    return payload.energized   # heartbeat confirms device-reported state


async def _bulk_insert_telemetry(
    db: AsyncSession,
    payloads: List[TelemetryPayload],
    received_at: datetime,
) -> Set[Tuple[str, int]]:
    """
    Bulk-INSERT telemetry events with ON CONFLICT DO NOTHING.

    Returns the set of (device_id, seq) tuples that were **actually inserted**
    (i.e. not duplicates).  Uses RETURNING to identify new rows without a
    second query.
    """
    values = [
        {
            "device_id": p.device_id,
            "pole_id": p.pole_id,
            "event": p.event,
            "energized": p.energized,
            "ts": p.ts,
            "seq": p.seq,
            "battery_mv": p.battery_mv,
            "rssi": p.rssi,
            "fw": p.fw,
            "received_at": received_at,
        }
        for p in payloads
    ]

    stmt = (
        pg_insert(TelemetryEvent)
        .values(values)
        .on_conflict_do_nothing(constraint="uq_telemetry_device_seq")
        .returning(TelemetryEvent.device_id, TelemetryEvent.seq)
    )
    result = await db.execute(stmt)
    await db.commit()
    return {(row.device_id, row.seq) for row in result.fetchall()}


async def _fetch_valid_pole_ids(
    db: AsyncSession,
    pole_ids: List[str],
) -> Set[str]:
    """
    Return the subset of ``pole_ids`` that actually exist in the ``poles`` table.

    Uses a single IN-query for efficiency.
    """
    if not pole_ids:
        return set()
    result = await db.execute(
        select(Pole.id).where(Pole.id.in_(pole_ids))
    )
    return {row[0] for row in result.fetchall()}


def _build_state_change_event(payload: TelemetryPayload, new_energized: bool) -> str:
    """Serialise a state-change event for pub/sub."""
    return json.dumps({
        "pole_id": payload.pole_id,
        "energized": new_energized,
        "event": payload.event.value,
        "ts": payload.ts.isoformat(),
        "device_id": payload.device_id,
    })


async def _apply_redis_updates(
    redis: aioredis.Redis,
    updates: List[Tuple[TelemetryPayload, bool, bool]],
) -> int:
    """
    Apply Redis state updates and publish state-change events.

    Parameters
    ----------
    updates : list of (payload, new_energized, state_changed)

    Returns the number of state changes published.

    Uses two non-transactional pipelines for maximum throughput:
      1. One pipeline for all HSET / SADD / SREM operations.
      2. One pipeline for all PUBLISH calls (only for changed poles).
    """
    if not updates:
        return 0

    # ── Pipeline 1: state writes ───────────────────────────────────────────────
    write_pipe = redis.pipeline(transaction=False)
    publish_messages: List[str] = []

    for payload, new_energized, state_changed in updates:
        pole_key = POLE_HASH_KEY.format(payload.pole_id)
        write_pipe.hset(pole_key, mapping={
            "energized": "1" if new_energized else "0",
            "last_seen": payload.ts.isoformat(),
            "last_event": payload.event.value,
            "device_id": payload.device_id,
            "seq": str(payload.seq),
        })
        if new_energized:
            write_pipe.sadd(POLES_LIVE_KEY, payload.pole_id)
            write_pipe.srem(POLES_DARK_KEY, payload.pole_id)
        else:
            write_pipe.sadd(POLES_DARK_KEY, payload.pole_id)
            write_pipe.srem(POLES_LIVE_KEY, payload.pole_id)

        if state_changed:
            publish_messages.append(_build_state_change_event(payload, new_energized))

    await write_pipe.execute()

    # ── Pipeline 2: publish state changes ─────────────────────────────────────
    if publish_messages:
        pub_pipe = redis.pipeline(transaction=False)
        for msg in publish_messages:
            pub_pipe.publish(STATE_CHANGE_CHANNEL, msg)
        await pub_pipe.execute()

    return len(publish_messages)


async def _process_payloads_for_redis(
    redis: aioredis.Redis,
    valid_payloads: List[TelemetryPayload],
) -> Tuple[int, int]:
    """
    For a list of valid (pole exists, newly inserted) payloads:

      1. Fetch current Redis state for all poles in one pipeline.
      2. Determine which are stale (seq ≤ current Redis seq).
      3. Apply state updates for non-stale payloads in one pipeline.

    When multiple payloads in the same batch target the same pole, only
    the one with the highest seq is applied (last writer wins within a batch).

    Returns (n_stale, n_state_changes).
    """
    if not valid_payloads:
        return 0, 0

    # Deduplicate per pole: keep highest-seq payload per pole_id
    latest_per_pole: Dict[str, TelemetryPayload] = {}
    for p in valid_payloads:
        existing = latest_per_pole.get(p.pole_id)
        if existing is None or p.seq > existing.seq:
            latest_per_pole[p.pole_id] = p

    deduped = list(latest_per_pole.values())

    # ── Batch-fetch current Redis state ────────────────────────────────────────
    read_pipe = redis.pipeline(transaction=False)
    for p in deduped:
        read_pipe.hgetall(POLE_HASH_KEY.format(p.pole_id))
    current_states: List[Dict[str, Any]] = await read_pipe.execute()

    # ── Classify: stale vs. to-apply ──────────────────────────────────────────
    n_stale = 0
    updates: List[Tuple[TelemetryPayload, bool, bool]] = []  # (payload, new_energized, state_changed)

    for payload, current in zip(deduped, current_states):
        current_seq = int(current.get("seq", -1))
        if payload.seq <= current_seq:
            n_stale += 1
            logger.debug(
                "Stale message: pole %s device %s seq %d ≤ current %d",
                payload.pole_id, payload.device_id, payload.seq, current_seq,
            )
            continue

        new_energized = _new_energized_value(payload)

        # Detect state change
        current_energized_str = current.get("energized")
        if current_energized_str is None:
            # First telemetry ever — treat as a state change to record initial state
            state_changed = True
        else:
            was_energized = current_energized_str == "1"
            state_changed = was_energized != new_energized

        updates.append((payload, new_energized, state_changed))

    n_state_changes = await _apply_redis_updates(redis, updates)
    return n_stale, n_state_changes


# ── API endpoints ──────────────────────────────────────────────────────────────


@router.post(
    "/telemetry",
    response_model=IngestResponse,
    status_code=200,
    summary="Ingest a single telemetry event from a pole device",
    description=(
        "Validates, deduplicates, persists to PostgreSQL, and updates the "
        "real-time Redis state for one telemetry event.  Duplicate packets "
        "(same device_id + seq) are silently ignored."
    ),
)
async def ingest_single(
    payload: TelemetryPayload,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> IngestResponse:
    received_at = datetime.now(timezone.utc)

    # ── INSERT with deduplication ──────────────────────────────────────────────
    inserted_keys = await _bulk_insert_telemetry(db, [payload], received_at)

    if not inserted_keys:
        # (device_id, seq) pair already exists → duplicate
        return IngestResponse(
            status="duplicate",
            device_id=payload.device_id,
            pole_id=payload.pole_id,
        )

    # ── Validate pole_id ───────────────────────────────────────────────────────
    valid_poles = await _fetch_valid_pole_ids(db, [payload.pole_id])
    if payload.pole_id not in valid_poles:
        logger.warning(
            "Telemetry from unknown pole %r (device %r) — stored but Redis skipped",
            payload.pole_id,
            payload.device_id,
        )
        return IngestResponse(
            status="ok",
            device_id=payload.device_id,
            pole_id=payload.pole_id,
            state_changed=False,
            stale=False,
        )

    # ── Update Redis ───────────────────────────────────────────────────────────
    n_stale, n_changes = await _process_payloads_for_redis(redis, [payload])
    return IngestResponse(
        status="ok",
        device_id=payload.device_id,
        pole_id=payload.pole_id,
        state_changed=n_changes > 0,
        stale=n_stale > 0,
    )


@router.post(
    "/telemetry/batch",
    response_model=BatchIngestResponse,
    status_code=200,
    summary="Ingest up to 500 telemetry events in one request",
    description=(
        "High-throughput batch ingestion endpoint. All payloads are inserted "
        "in a single bulk SQL statement and Redis is updated using pipelines "
        "to maximise throughput. Target: ≥500 msg/s sustained."
    ),
)
async def ingest_batch(
    payloads: List[TelemetryPayload],
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> BatchIngestResponse:
    total = len(payloads)

    if total == 0:
        return BatchIngestResponse(
            status="ok", total=0, inserted=0, duplicates=0, stale=0, state_changes=0
        )
    if total > 500:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {total} exceeds the maximum of 500.",
        )

    received_at = datetime.now(timezone.utc)

    # ── Bulk INSERT with RETURNING ─────────────────────────────────────────────
    inserted_keys = await _bulk_insert_telemetry(db, payloads, received_at)
    n_inserted = len(inserted_keys)
    n_duplicates = total - n_inserted

    if n_inserted == 0:
        return BatchIngestResponse(
            status="ok",
            total=total,
            inserted=0,
            duplicates=n_duplicates,
            stale=0,
            state_changes=0,
        )

    # ── Identify newly inserted payloads ──────────────────────────────────────
    new_payloads = [
        p for p in payloads
        if (p.device_id, p.seq) in inserted_keys
    ]

    # ── Validate pole_ids in one DB round-trip ────────────────────────────────
    unique_pole_ids = list({p.pole_id for p in new_payloads})
    valid_pole_ids = await _fetch_valid_pole_ids(db, unique_pole_ids)

    unknown_poles = set(unique_pole_ids) - valid_pole_ids
    if unknown_poles:
        logger.warning(
            "Batch contains telemetry for %d unknown pole(s): %s — stored, Redis skipped",
            len(unknown_poles),
            sorted(unknown_poles),
        )

    valid_payloads = [p for p in new_payloads if p.pole_id in valid_pole_ids]

    # ── Redis state updates ────────────────────────────────────────────────────
    n_stale, n_state_changes = await _process_payloads_for_redis(redis, valid_payloads)

    return BatchIngestResponse(
        status="ok",
        total=total,
        inserted=n_inserted,
        duplicates=n_duplicates,
        stale=n_stale,
        state_changes=n_state_changes,
    )
