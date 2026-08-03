"""
Network topology API - exposes the power grid data for the frontend map
and any external consumers.

Endpoints
---------
GET /api/network/substations          -> all substations
GET /api/network/feeders              -> all feeders
GET /api/network/transformers         -> all distribution transformers
GET /api/network/poles                -> all poles, optionally filtered by ?dt_id=
GET /api/network/stats                -> aggregate counts
GET /api/network/topology/{dt_id}     -> full radial tree for one DT (from memory)
GET /api/network/topology-summary     -> per-DT summary table (from memory)
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.pole import DistributionTransformer, Feeder, Pole, Substation

router = APIRouter(prefix="/api/network", tags=["network"])


# ----------- Response schemas ------------------------------------------------


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
    id: str
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    pole_type: str
    ward: Optional[str]
    pincode: Optional[str]
    has_topology: bool
    seq_on_line: Optional[int]
    parent_pole_id: Optional[str]
    energized: bool
    has_device: bool


class NetworkStats(BaseModel):
    total_substations: int
    total_feeders: int
    total_dts: int
    dts_with_topology: int
    total_poles: int
    poles_with_devices: int
    poles_with_topology: int


# ----------- Topology schemas (in-memory) ------------------------------------


class TopologyPoleOut(BaseModel):
    pole_id: str
    lat: float
    lon: float
    dt_id: str
    feeder_id: str
    device_id: Optional[str]
    pincode: Optional[str]
    ward: Optional[str]
    parent_id: Optional[str]
    children: List[str]
    seq_on_line: Optional[int]
    topology_source: str
    depth: int
    has_device: bool


class TopologyTreeOut(BaseModel):
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: int
    households_served: int
    topology_source: str
    total_poles: int
    poles_with_device: int
    root_poles: List[str]
    poles: List[TopologyPoleOut]


class TopologySummaryItem(BaseModel):
    dt_id: str
    feeder_id: str
    topology_source: str
    total_poles: int
    poles_with_device: int
    root_pole_count: int
    max_depth: int


# ----------- DB-backed endpoints --------------------------------------------


@router.get("/substations", response_model=List[SubstationOut], summary="List all substations")
async def get_substations(db: AsyncSession = Depends(get_db)):
    """Return all 66/11 kV substations ordered by ID."""
    result = await db.execute(select(Substation).order_by(Substation.id))
    return result.scalars().all()


@router.get("/feeders", response_model=List[FeederOut], summary="List all feeders")
async def get_feeders(db: AsyncSession = Depends(get_db)):
    """Return all 11 kV feeders with their parent substation IDs."""
    result = await db.execute(select(Feeder).order_by(Feeder.id))
    return result.scalars().all()


@router.get("/transformers", response_model=List[TransformerOut], summary="List all distribution transformers")
async def get_transformers(db: AsyncSession = Depends(get_db)):
    """Return all DTs with geographic and capacity information."""
    result = await db.execute(select(DistributionTransformer).order_by(DistributionTransformer.id))
    return result.scalars().all()


@router.get("/poles", response_model=List[PoleOut], summary="List poles, optionally filtered by DT")
async def get_poles(
    dt_id: Optional[str] = Query(None, description="Filter to poles belonging to a specific DT"),
    db: AsyncSession = Depends(get_db),
):
    """Return LT poles. Without dt_id returns all poles; with dt_id returns only that DT's poles."""
    stmt = select(Pole)
    if dt_id:
        stmt = stmt.where(Pole.dt_id == dt_id)
    stmt = stmt.order_by(Pole.id)
    result = await db.execute(stmt)
    poles = result.scalars().all()
    return [
        PoleOut(
            id=p.id, dt_id=p.dt_id, feeder_id=p.feeder_id, lat=p.lat, lon=p.lon,
            pole_type=p.pole_type, ward=p.ward, pincode=p.pincode,
            has_topology=p.has_topology, seq_on_line=p.seq_on_line,
            parent_pole_id=p.parent_pole_id, energized=True,
            has_device=p.device_id is not None,
        )
        for p in poles
    ]


@router.get("/stats", response_model=NetworkStats, summary="Aggregate network statistics")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Return count-level metrics for the entire distribution network."""
    total_ss = (await db.execute(select(func.count(Substation.id)))).scalar_one()
    total_feeders = (await db.execute(select(func.count(Feeder.id)))).scalar_one()
    total_dts = (await db.execute(select(func.count(DistributionTransformer.id)))).scalar_one()
    dts_with_topo = (
        await db.execute(select(func.count(func.distinct(Pole.dt_id))).where(Pole.has_topology.is_(True)))
    ).scalar_one()
    total_poles = (await db.execute(select(func.count(Pole.id)))).scalar_one()
    poles_with_devices = (
        await db.execute(select(func.count(Pole.id)).where(Pole.device_id.isnot(None)))
    ).scalar_one()
    poles_with_topo = (
        await db.execute(select(func.count(Pole.id)).where(Pole.has_topology.is_(True)))
    ).scalar_one()
    return NetworkStats(
        total_substations=total_ss, total_feeders=total_feeders, total_dts=total_dts,
        dts_with_topology=dts_with_topo, total_poles=total_poles,
        poles_with_devices=poles_with_devices, poles_with_topology=poles_with_topo,
    )


# ----------- In-memory topology endpoints ------------------------------------


def _get_topo(request: Request):
    """Retrieve NetworkTopology from app state; raise 503 if not ready."""
    topo = getattr(request.app.state, "topology", None)
    if topo is None:
        raise HTTPException(
            status_code=503,
            detail="Topology graph is not yet available - startup may still be in progress.",
        )
    return topo


@router.get(
    "/topology/{dt_id}",
    response_model=TopologyTreeOut,
    summary="Full radial tree for a single DT",
    description=(
        "Returns the complete pole tree for the specified distribution transformer "
        "from the in-memory topology graph. Each pole includes its parent_id, children, "
        "depth, topology_source, and GPS coordinates. The frontend map uses this to "
        "draw tree lines between poles. topology_source is 'known' for the ~40% of DTs "
        "with wired topology data and 'inferred' for the remaining ~60% built geometrically."
    ),
)
async def get_dt_topology(dt_id: str, request: Request) -> TopologyTreeOut:
    """
    Return the full radial tree for dt_id.

    Zero-DB endpoint: all data is read from the in-memory NetworkTopology built at startup.
    """
    topo = _get_topo(request)
    tree = topo.transformers.get(dt_id)
    if tree is None:
        raise HTTPException(status_code=404, detail=f"DT '{dt_id}' not found in topology.")

    pole_list: List[TopologyPoleOut] = [
        TopologyPoleOut(
            pole_id=node.pole_id, lat=node.lat, lon=node.lon,
            dt_id=node.dt_id, feeder_id=node.feeder_id,
            device_id=node.device_id, pincode=node.pincode, ward=node.ward,
            parent_id=node.parent_id, children=node.children,
            seq_on_line=node.seq_on_line, topology_source=node.topology_source,
            depth=node.depth, has_device=node.device_id is not None,
        )
        for node in tree.poles.values()
    ]
    return TopologyTreeOut(
        dt_id=tree.dt_id, feeder_id=tree.feeder_id, lat=tree.lat, lon=tree.lon,
        capacity_kva=tree.capacity_kva, households_served=tree.households_served,
        topology_source=tree.topology_source, total_poles=tree.total_poles,
        poles_with_device=tree.poles_with_device, root_poles=tree.root_poles,
        poles=pole_list,
    )


@router.get(
    "/topology-summary",
    response_model=List[TopologySummaryItem],
    summary="Per-DT topology summary table",
    description=(
        "Returns a compact summary row for every DT: pole count, topology source "
        "(known/inferred), number of root poles, and maximum tree depth. "
        "Useful for dashboards and quickly identifying DTs with unreliable inferred topology."
    ),
)
async def get_topology_summary(
    request: Request,
    feeder_id: Optional[str] = Query(None, description="Filter to a specific feeder, e.g. F-01-01"),
) -> List[TopologySummaryItem]:
    """Return a per-DT summary from the in-memory topology graph. Zero-DB endpoint."""
    topo = _get_topo(request)
    dt_ids = topo.feeder_dts.get(feeder_id, []) if feeder_id else list(topo.transformers.keys())
    items: List[TopologySummaryItem] = []
    for dt_id in sorted(dt_ids):
        tree = topo.transformers.get(dt_id)
        if tree is None:
            continue
        summary: Dict[str, Any] = tree.to_summary_dict()
        items.append(TopologySummaryItem(
            dt_id=summary["dt_id"], feeder_id=summary["feeder_id"],
            topology_source=summary["topology_source"], total_poles=summary["total_poles"],
            poles_with_device=summary["poles_with_device"],
            root_pole_count=summary["root_pole_count"], max_depth=summary["max_depth"],
        ))
    return items
