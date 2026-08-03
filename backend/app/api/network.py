"""
Network topology API — exposes the power grid data for the frontend map
and any external consumers.

Endpoints
---------
GET /api/network/substations    → all substations
GET /api/network/feeders        → all feeders
GET /api/network/transformers   → all distribution transformers
GET /api/network/poles          → all poles, optionally filtered by ?dt_id=
GET /api/network/stats          → aggregate counts
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.pole import DistributionTransformer, Feeder, Pole, Substation

router = APIRouter(prefix="/api/network", tags=["network"])


# ── Response schemas ───────────────────────────────────────────────────────────


class SubstationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lat: float
    lon: float


class FeederOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    substation_id: int
    name: str


class TransformerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: int
    households_served: int


class PoleOut(BaseModel):
    """
    Pole representation for the API.

    ``energized`` is a placeholder (always True until real telemetry is ingested).
    ``has_device`` indicates whether an IoT device is physically fitted.
    """

    id: str
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    pole_type: str
    ward: Optional[str]
    pincode: Optional[str]
    # Topology
    has_topology: bool
    seq_on_line: Optional[int]
    parent_pole_id: Optional[str]
    # Status
    energized: bool    # placeholder — always True pre-telemetry
    has_device: bool   # True if device_id IS NOT NULL


class NetworkStats(BaseModel):
    total_substations: int
    total_feeders: int
    total_dts: int
    dts_with_topology: int
    total_poles: int
    poles_with_devices: int
    poles_with_topology: int


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/substations",
    response_model=List[SubstationOut],
    summary="List all substations",
)
async def get_substations(db: AsyncSession = Depends(get_db)):
    """Return all 66/11 kV substations ordered by ID."""
    result = await db.execute(select(Substation).order_by(Substation.id))
    return result.scalars().all()


@router.get(
    "/feeders",
    response_model=List[FeederOut],
    summary="List all feeders",
)
async def get_feeders(db: AsyncSession = Depends(get_db)):
    """Return all 11 kV feeders with their parent substation IDs."""
    result = await db.execute(select(Feeder).order_by(Feeder.id))
    return result.scalars().all()


@router.get(
    "/transformers",
    response_model=List[TransformerOut],
    summary="List all distribution transformers",
)
async def get_transformers(db: AsyncSession = Depends(get_db)):
    """Return all DTs with geographic and capacity information."""
    result = await db.execute(
        select(DistributionTransformer).order_by(DistributionTransformer.id)
    )
    return result.scalars().all()


@router.get(
    "/poles",
    response_model=List[PoleOut],
    summary="List poles, optionally filtered by DT",
)
async def get_poles(
    dt_id: Optional[str] = Query(
        None,
        description="Filter to poles belonging to a specific distribution transformer, e.g. D-0001",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return LT poles.

    - Without ``dt_id``: returns **all** poles (~3 000–4 000 rows).
    - With ``dt_id``: returns only poles under that distribution transformer.
    """
    stmt = select(Pole)
    if dt_id:
        stmt = stmt.where(Pole.dt_id == dt_id)
    stmt = stmt.order_by(Pole.id)

    result = await db.execute(stmt)
    poles = result.scalars().all()

    return [
        PoleOut(
            id=p.id,
            dt_id=p.dt_id,
            feeder_id=p.feeder_id,
            lat=p.lat,
            lon=p.lon,
            pole_type=p.pole_type,
            ward=p.ward,
            pincode=p.pincode,
            has_topology=p.has_topology,
            seq_on_line=p.seq_on_line,
            parent_pole_id=p.parent_pole_id,
            energized=True,          # placeholder until telemetry engine runs
            has_device=p.device_id is not None,
        )
        for p in poles
    ]


@router.get(
    "/stats",
    response_model=NetworkStats,
    summary="Aggregate network statistics",
)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """
    Return count-level metrics for the entire distribution network.

    ``dts_with_topology`` counts DTs that have at least one pole with
    ``has_topology = True`` (i.e. the ~40 % group with known wiring order).
    """
    total_ss = (
        await db.execute(select(func.count(Substation.id)))
    ).scalar_one()

    total_feeders = (
        await db.execute(select(func.count(Feeder.id)))
    ).scalar_one()

    total_dts = (
        await db.execute(select(func.count(DistributionTransformer.id)))
    ).scalar_one()

    # DTs that have at least one topology-enabled pole
    dts_with_topo = (
        await db.execute(
            select(func.count(func.distinct(Pole.dt_id))).where(
                Pole.has_topology.is_(True)
            )
        )
    ).scalar_one()

    total_poles = (
        await db.execute(select(func.count(Pole.id)))
    ).scalar_one()

    poles_with_devices = (
        await db.execute(
            select(func.count(Pole.id)).where(Pole.device_id.isnot(None))
        )
    ).scalar_one()

    poles_with_topo = (
        await db.execute(
            select(func.count(Pole.id)).where(Pole.has_topology.is_(True))
        )
    ).scalar_one()

    return NetworkStats(
        total_substations=total_ss,
        total_feeders=total_feeders,
        total_dts=total_dts,
        dts_with_topology=dts_with_topo,
        total_poles=total_poles,
        poles_with_devices=poles_with_devices,
        poles_with_topology=poles_with_topo,
    )
